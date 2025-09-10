#!/usr/bin/env python3
"""
LUNA Chart Generator - Railway Web Service
Generates candlestick charts and uploads to Supabase S3
"""

from flask import Flask, jsonify, request, send_file
import plotly.graph_objects as go
import plotly.io as pio
import requests
import datetime
import os
import io
import numpy as np
from plotly.subplots import make_subplots
from supabase import create_client, Client
from dotenv import load_dotenv
import base64
import openai
import json

# Load environment variables
load_dotenv()

app = Flask(__name__)

def get_supabase_client():
    """Initialize Supabase client with Service Role Key for uploads"""
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    
    if not url or not key:
        raise ValueError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set in environment variables")
    
    return create_client(url, key)

def fetch_luna_data(days=1):
    """Fetch LUNA OHLC data from CoinGecko"""
    url = f"https://api.coingecko.com/api/v3/coins/luna-by-virtuals/ohlc?vs_currency=usd&days={days}"
    headers = {"x-cg-demo-api-key": "REMOVED"}
    
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"Error fetching data: {e}")
        return []

def calculate_moving_averages(prices, periods=[20, 50]):
    """Calculate Simple Moving Averages"""
    ma_data = {}
    for period in periods:
        if len(prices) >= period:
            ma_values = []
            for i in range(len(prices)):
                if i < period - 1:
                    ma_values.append(None)
                else:
                    ma_values.append(sum(prices[i-period+1:i+1]) / period)
            ma_data[f'MA{period}'] = ma_values
    return ma_data

def calculate_rsi(prices, period=14):
    """Calculate Relative Strength Index"""
    if len(prices) < period + 1:
        return [None] * len(prices)
    
    deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
    gains = [delta if delta > 0 else 0 for delta in deltas]
    losses = [-delta if delta < 0 else 0 for delta in deltas]
    
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    
    rsi_values = [None] * period
    
    for i in range(period, len(prices)):
        if avg_loss == 0:
            rsi_values.append(100)
        else:
            rs = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))
            rsi_values.append(rsi)
        
        # Update averages
        if i < len(prices) - 1:
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    
    return rsi_values

def detect_trend_lines(timestamps, highs, lows, closes):
    """Detect support and resistance trend lines"""
    trend_lines = []
    
    # Find significant highs and lows
    window = max(3, len(highs) // 10)  # Adaptive window size
    
    # Find resistance levels (significant highs)
    resistance_points = []
    for i in range(window, len(highs) - window):
        if highs[i] == max(highs[i-window:i+window+1]):
            resistance_points.append((i, highs[i], timestamps[i]))
    
    # Find support levels (significant lows)
    support_points = []
    for i in range(window, len(lows) - window):
        if lows[i] == min(lows[i-window:i+window+1]):
            support_points.append((i, lows[i], timestamps[i]))
    
    # Create trend lines from recent significant points
    if len(resistance_points) >= 2:
        # Take the two most recent resistance points
        recent_resistance = sorted(resistance_points, key=lambda x: x[0])[-2:]
        if len(recent_resistance) == 2:
            x1, y1, t1 = recent_resistance[0]
            x2, y2, t2 = recent_resistance[1]
            
            # Calculate slope and extend line
            slope = (y2 - y1) / (x2 - x1) if x2 != x1 else 0
            trend_lines.append({
                'type': 'resistance',
                'x': [t1, t2, timestamps[-1]],
                'y': [y1, y2, y2 + slope * (len(timestamps) - 1 - x2)],
                'color': '#FF6B6B',
                'dash': 'dash'
            })
    
    if len(support_points) >= 2:
        # Take the two most recent support points
        recent_support = sorted(support_points, key=lambda x: x[0])[-2:]
        if len(recent_support) == 2:
            x1, y1, t1 = recent_support[0]
            x2, y2, t2 = recent_support[1]
            
            # Calculate slope and extend line
            slope = (y2 - y1) / (x2 - x1) if x2 != x1 else 0
            trend_lines.append({
                'type': 'support',
                'x': [t1, t2, timestamps[-1]],
                'y': [y1, y2, y2 + slope * (len(timestamps) - 1 - x2)],
                'color': '#4ECDC4',
                'dash': 'dash'
            })
    
    return trend_lines

def detect_advanced_patterns(timestamps, highs, lows, closes, volumes):
    """Detect all major chart patterns"""
    patterns = []
    
    if len(closes) < 10:
        return patterns
    
    # Reversal Patterns
    patterns.extend(detect_head_and_shoulders(highs, lows, closes, timestamps))
    patterns.extend(detect_double_tops_bottoms(highs, lows, closes, timestamps))
    patterns.extend(detect_wedges(highs, lows, closes, timestamps))
    
    # Continuation Patterns
    patterns.extend(detect_cup_and_handle(highs, lows, closes, timestamps))
    
    # Legacy triangle detection (keep for backward compatibility)
    recent_highs = highs[-10:]
    recent_lows = lows[-10:]
    
    # Ascending triangle
    if len(recent_highs) >= 5:
        high_variance = np.var(recent_highs[-5:])
        low_trend = np.polyfit(range(5), recent_lows[-5:], 1)[0]
        
        if high_variance < 0.0001 and low_trend > 0:
            patterns.append({
                'type': 'Ascending Triangle',
                'description': 'Bullish continuation pattern - horizontal resistance with rising support',
                'confidence': 'Medium',
                'pattern_data': {
                    'resistance_level': np.mean(recent_highs[-5:]),
                    'support_trend': low_trend,
                    'breakout_direction': 'Upward'
                }
            })
    
    # Descending triangle
    if len(recent_lows) >= 5:
        low_variance = np.var(recent_lows[-5:])
        high_trend = np.polyfit(range(5), recent_highs[-5:], 1)[0]
        
        if low_variance < 0.0001 and high_trend < 0:
            patterns.append({
                'type': 'Descending Triangle',
                'description': 'Bearish continuation pattern - horizontal support with falling resistance',
                'confidence': 'Medium',
                'pattern_data': {
                    'support_level': np.mean(recent_lows[-5:]),
                    'resistance_trend': high_trend,
                    'breakout_direction': 'Downward'
                }
            })
    
    return patterns

def detect_head_and_shoulders(highs, lows, closes, timestamps):
    """Detect Head and Shoulders pattern"""
    patterns = []
    
    if len(highs) < 15:
        return patterns
    
    # Look for three peaks with middle peak higher
    for i in range(5, len(highs) - 10):
        # Left shoulder
        left_shoulder_idx = i
        left_shoulder_price = highs[i]
        
        # Head (highest peak)
        head_start = i + 2
        head_end = i + 8
        if head_end >= len(highs):
            continue
            
        head_idx = np.argmax(highs[head_start:head_end]) + head_start
        head_price = highs[head_idx]
        
        # Right shoulder
        right_shoulder_start = head_idx + 2
        right_shoulder_end = head_idx + 8
        if right_shoulder_end >= len(highs):
            continue
            
        right_shoulder_idx = np.argmax(highs[right_shoulder_start:right_shoulder_end]) + right_shoulder_start
        right_shoulder_price = highs[right_shoulder_idx]
        
        # Validate Head and Shoulders pattern
        if (head_price > left_shoulder_price and 
            head_price > right_shoulder_price and
            abs(left_shoulder_price - right_shoulder_price) / left_shoulder_price < 0.05):  # Shoulders roughly equal
            
            # Calculate neckline (support level)
            neckline = min(lows[left_shoulder_idx:right_shoulder_idx])
            
            patterns.append({
                'type': 'Head and Shoulders',
                'description': 'Bearish reversal pattern - three peaks with middle highest',
                'confidence': 'High',
                'pattern_data': {
                    'left_shoulder': {'idx': left_shoulder_idx, 'price': left_shoulder_price, 'time': timestamps[left_shoulder_idx]},
                    'head': {'idx': head_idx, 'price': head_price, 'time': timestamps[head_idx]},
                    'right_shoulder': {'idx': right_shoulder_idx, 'price': right_shoulder_price, 'time': timestamps[right_shoulder_idx]},
                    'neckline': neckline,
                    'target': neckline - (head_price - neckline)
                }
            })
            break
    
    return patterns

def detect_double_tops_bottoms(highs, lows, closes, timestamps):
    """Detect Double Top and Double Bottom patterns"""
    patterns = []
    
    if len(highs) < 10:
        return patterns
    
    # Double Top detection
    for i in range(3, len(highs) - 5):
        first_peak = highs[i]
        second_peak_start = i + 3
        second_peak_end = i + 8
        if second_peak_end >= len(highs):
            continue
            
        second_peak_idx = np.argmax(highs[second_peak_start:second_peak_end]) + second_peak_start
        second_peak = highs[second_peak_idx]
        
        # Validate double top
        if abs(first_peak - second_peak) / first_peak < 0.03:  # Peaks within 3%
            trough_idx = np.argmin(lows[i:second_peak_idx]) + i
            trough_price = lows[trough_idx]
            
            patterns.append({
                'type': 'Double Top',
                'description': 'Bearish reversal pattern - two equal peaks',
                'confidence': 'Medium',
                'pattern_data': {
                    'first_peak': {'idx': i, 'price': first_peak, 'time': timestamps[i]},
                    'second_peak': {'idx': second_peak_idx, 'price': second_peak, 'time': timestamps[second_peak_idx]},
                    'trough': {'idx': trough_idx, 'price': trough_price, 'time': timestamps[trough_idx]},
                    'target': trough_price - (first_peak - trough_price)
                }
            })
    
    # Double Bottom detection
    for i in range(3, len(lows) - 5):
        first_trough = lows[i]
        second_trough_start = i + 3
        second_trough_end = i + 8
        if second_trough_end >= len(lows):
            continue
            
        second_trough_idx = np.argmin(lows[second_trough_start:second_trough_end]) + second_trough_start
        second_trough = lows[second_trough_idx]
        
        # Validate double bottom
        if abs(first_trough - second_trough) / first_trough < 0.03:  # Troughs within 3%
            peak_idx = np.argmax(highs[i:second_trough_idx]) + i
            peak_price = highs[peak_idx]
            
            patterns.append({
                'type': 'Double Bottom',
                'description': 'Bullish reversal pattern - two equal troughs',
                'confidence': 'Medium',
                'pattern_data': {
                    'first_trough': {'idx': i, 'price': first_trough, 'time': timestamps[i]},
                    'second_trough': {'idx': second_trough_idx, 'price': second_trough, 'time': timestamps[second_trough_idx]},
                    'peak': {'idx': peak_idx, 'price': peak_price, 'time': timestamps[peak_idx]},
                    'target': peak_price + (peak_price - first_trough)
                }
            })
    
    return patterns

def detect_cup_and_handle(highs, lows, closes, timestamps):
    """Detect Cup and Handle pattern"""
    patterns = []
    
    if len(closes) < 20:
        return patterns
    
    # Look for cup formation (U-shaped decline and recovery)
    for i in range(10, len(closes) - 10):
        # Cup formation (first 2/3 of data)
        cup_data = closes[i-10:i+5]
        cup_start = cup_data[0]
        cup_bottom = min(cup_data)
        cup_end = cup_data[-1]
        
        # Handle formation (last 1/3 of data)
        handle_data = closes[i+5:i+10]
        handle_start = handle_data[0]
        handle_end = handle_data[-1]
        
        # Validate cup and handle
        cup_depth = (cup_start - cup_bottom) / cup_start
        cup_recovery = (cup_end - cup_bottom) / cup_bottom
        handle_retracement = (handle_start - handle_end) / handle_start
        
        if (cup_depth > 0.05 and cup_depth < 0.5 and  # Cup depth 5-50%
            cup_recovery > 0.3 and  # Cup recovers at least 30%
            handle_retracement > 0.02 and handle_retracement < 0.2):  # Handle retraces 2-20%
            
            patterns.append({
                'type': 'Cup and Handle',
                'description': 'Bullish continuation pattern - U-shaped cup with small handle',
                'confidence': 'High',
                'pattern_data': {
                    'cup_start': {'idx': i-10, 'price': cup_start, 'time': timestamps[i-10]},
                    'cup_bottom': {'idx': i-10+np.argmin(cup_data), 'price': cup_bottom, 'time': timestamps[i-10+np.argmin(cup_data)]},
                    'cup_end': {'idx': i+4, 'price': cup_end, 'time': timestamps[i+4]},
                    'handle_start': {'idx': i+5, 'price': handle_start, 'time': timestamps[i+5]},
                    'handle_end': {'idx': i+9, 'price': handle_end, 'time': timestamps[i+9]},
                    'target': cup_start + (cup_start - cup_bottom)
                }
            })
            break
    
    return patterns

def detect_wedges(highs, lows, closes, timestamps):
    """Detect Rising and Falling Wedge patterns"""
    patterns = []
    
    if len(highs) < 15:
        return patterns
    
    # Rising Wedge (bearish)
    recent_highs = highs[-10:]
    recent_lows = lows[-10:]
    
    if len(recent_highs) >= 8:
        high_trend = np.polyfit(range(len(recent_highs)), recent_highs, 1)[0]
        low_trend = np.polyfit(range(len(recent_lows)), recent_lows, 1)[0]
        
        if high_trend > 0 and low_trend > 0 and high_trend > low_trend:
            patterns.append({
                'type': 'Rising Wedge',
                'description': 'Bearish reversal pattern - converging rising lines',
                'confidence': 'Medium',
                'pattern_data': {
                    'resistance_line': {'slope': high_trend, 'start_price': recent_highs[0]},
                    'support_line': {'slope': low_trend, 'start_price': recent_lows[0]},
                    'convergence': True
                }
            })
    
    # Falling Wedge (bullish)
    if len(recent_highs) >= 8:
        high_trend = np.polyfit(range(len(recent_highs)), recent_highs, 1)[0]
        low_trend = np.polyfit(range(len(recent_lows)), recent_lows, 1)[0]
        
        if high_trend < 0 and low_trend < 0 and abs(high_trend) > abs(low_trend):
            patterns.append({
                'type': 'Falling Wedge',
                'description': 'Bullish reversal pattern - converging falling lines',
                'confidence': 'Medium',
                'pattern_data': {
                    'resistance_line': {'slope': high_trend, 'start_price': recent_highs[0]},
                    'support_line': {'slope': low_trend, 'start_price': recent_lows[0]},
                    'convergence': True
                }
            })
    
    return patterns

def analyze_patterns_with_llm(patterns, market_data, context):
    """Use ChatGPT LLM to intelligently analyze and select the best pattern"""
    try:
        # Initialize OpenAI client
        openai.api_key = os.getenv("OPENAI_API_KEY")
        
        if not openai.api_key:
            print("⚠️ OpenAI API key not found, using mathematical fallback")
            return None
        
        # Prepare pattern data for LLM
        pattern_summary = []
        for pattern in patterns[:10]:  # Limit to top 10 patterns
            pattern_summary.append({
                'type': pattern['type'],
                'description': pattern['description'],
                'confidence': pattern['confidence']
            })
        
        # Create LLM prompt
        prompt = f"""
        You are a professional cryptocurrency trading analyst. Analyze these detected chart patterns for LUNA/USD and select the BEST pattern for trading decisions.

        MARKET DATA:
        - Current Price: ${market_data['current_price']:.6f}
        - Price Change: {market_data['price_change_percent']:.2f}%
        - RSI: {market_data['rsi']:.1f} ({market_data['rsi_signal']})
        - MA20: ${market_data['ma20']:.6f}
        - Trend: {market_data['trend']}
        - Time Range: {market_data['time_range']}

        DETECTED PATTERNS:
        {json.dumps(pattern_summary, indent=2)}

        CONTEXT:
        {context}

        Please analyze and respond with ONLY a JSON object containing:
        {{
            "selected_pattern": "Pattern Name",
            "pattern_type": "Reversal/Continuation/Bilateral",
            "signal": "Bullish/Bearish/Neutral",
            "confidence": "High/Medium/Low",
            "trading_recommendation": "Buy/Sell/Hold",
            "price_target": "Expected price level",
            "reasoning": "Why this pattern was selected",
            "tweet_summary": "Short summary for social media (max 280 chars)"
        }}

        Focus on:
        1. Pattern reliability and historical success
        2. Current market conditions
        3. Risk/reward ratio
        4. Time to completion
        5. Overall market sentiment
        """
        
        # Call ChatGPT API
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are a professional cryptocurrency trading analyst with expertise in technical analysis and chart patterns."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=500,
            temperature=0.3
        )
        
        # Parse LLM response
        llm_response = response.choices[0].message.content.strip()
        
        # Try to extract JSON from response
        if "```json" in llm_response:
            json_start = llm_response.find("```json") + 7
            json_end = llm_response.find("```", json_start)
            json_str = llm_response[json_start:json_end].strip()
        else:
            json_str = llm_response
        
        # Parse JSON response
        llm_analysis = json.loads(json_str)
        
        print(f"✅ LLM Analysis: {llm_analysis['selected_pattern']} - {llm_analysis['signal']}")
        return llm_analysis
        
    except Exception as e:
        print(f"⚠️ LLM Analysis failed: {e}")
        return None

def select_best_pattern_mathematical(patterns):
    """Mathematical fallback for pattern selection"""
    if not patterns:
        return None
    
    # Score patterns by confidence and type
    pattern_scores = {}
    
    for pattern in patterns:
        score = 0
        
        # Confidence scoring
        if pattern['confidence'] == 'High':
            score += 100
        elif pattern['confidence'] == 'Medium':
            score += 50
        else:
            score += 25
        
        # Pattern type scoring (reversal patterns are more significant)
        if 'Head and Shoulders' in pattern['type']:
            score += 50
        elif 'Double' in pattern['type']:
            score += 30
        elif 'Triangle' in pattern['type']:
            score += 20
        elif 'Wedge' in pattern['type']:
            score += 25
        elif 'Cup and Handle' in pattern['type']:
            score += 40
        
        pattern_scores[pattern['type']] = score
    
    # Select highest scoring pattern
    best_pattern_type = max(pattern_scores, key=pattern_scores.get)
    best_pattern = next(p for p in patterns if p['type'] == best_pattern_type)
    
    # Determine signal based on pattern type
    signal = "Neutral"
    recommendation = "Hold"
    
    if "Head and Shoulders" in best_pattern['type'] or "Double Top" in best_pattern['type']:
        signal = "Bearish"
        recommendation = "Sell"
    elif "Double Bottom" in best_pattern['type'] or "Cup and Handle" in best_pattern['type']:
        signal = "Bullish"
        recommendation = "Buy"
    elif "Ascending Triangle" in best_pattern['type']:
        signal = "Bullish"
        recommendation = "Buy"
    elif "Descending Triangle" in best_pattern['type']:
        signal = "Bearish"
        recommendation = "Sell"
    
    return {
        "selected_pattern": best_pattern['type'],
        "pattern_type": "Reversal" if "Double" in best_pattern['type'] or "Head" in best_pattern['type'] else "Continuation",
        "signal": signal,
        "confidence": best_pattern['confidence'],
        "trading_recommendation": recommendation,
        "price_target": "TBD",
        "reasoning": f"Mathematically selected based on confidence score and pattern reliability",
        "tweet_summary": f"🎯 {best_pattern['type']} detected! {signal} signal - {recommendation} recommendation"
    }

def create_combined_multi_timeframe_chart(timeframe_results):
    """Create a combined chart with all 4 timeframes in one image"""
    try:
        # Create subplots for 4 timeframes (2x2 grid)
        fig = make_subplots(
            rows=2, cols=2,
            subplot_titles=[f"LUNA/USD {tf} Analysis" for tf in timeframe_results.keys()],
            vertical_spacing=0.08,
            horizontal_spacing=0.08,
            row_heights=[0.5, 0.5],
            column_widths=[0.5, 0.5]
        )
        
        # Professional color scheme
        colors = {
            'bullish': '#00D4AA',
            'bearish': '#FF6B6B',
            'neutral': '#8B5CF6',
            'background': '#0F0F23',
            'surface': '#1A1A2E',
            'text_primary': '#FFFFFF',
            'text_secondary': '#A0A0A0',
            'grid': '#2D2D44',
            'accent': '#00D4AA'
        }
        
        # Plot each timeframe
        positions = [(1, 1), (1, 2), (2, 1), (2, 2)]
        for i, (tf_name, tf_data) in enumerate(timeframe_results.items()):
            if i >= 4:  # Limit to 4 timeframes
                break
                
            row, col = positions[i]
            data = tf_data['data']
            technical = tf_data['technical']
            analysis = tf_data['analysis']
            
            timestamps = data['timestamps']
            highs = data['highs']
            lows = data['lows']
            closes = data['closes']
            volumes = data['volumes']
            
            # Add candlestick chart
            fig.add_trace(
                go.Candlestick(
                    x=timestamps,
                    open=[c for c in closes],  # Simplified for demo
                    high=highs,
                    low=lows,
                    close=closes,
                    name=f"{tf_name} Price",
                    increasing_line_color=colors['bullish'],
                    decreasing_line_color=colors['bearish'],
                    increasing_fillcolor=colors['bullish'],
                    decreasing_fillcolor=colors['bearish']
                ),
                row=row, col=col
            )
            
            # Add moving averages
            ma_data = technical['ma_data']
            if 'MA20' in ma_data and ma_data['MA20'][-1] is not None:
                fig.add_trace(
                    go.Scatter(
                        x=timestamps,
                        y=ma_data['MA20'],
                        mode='lines',
                        name=f"{tf_name} MA20",
                        line=dict(color=colors['accent'], width=2),
                        showlegend=False
                    ),
                    row=row, col=col
                )
            
            if 'MA50' in ma_data and ma_data['MA50'][-1] is not None:
                fig.add_trace(
                    go.Scatter(
                        x=timestamps,
                        y=ma_data['MA50'],
                        mode='lines',
                        name=f"{tf_name} MA50",
                        line=dict(color=colors['neutral'], width=2),
                        showlegend=False
                    ),
                    row=row, col=col
                )
            
            # Add pattern annotation
            if analysis:
                signal_color = colors['bullish'] if analysis['signal'] == 'Bullish' else colors['bearish'] if analysis['signal'] == 'Bearish' else colors['neutral']
                
                fig.add_annotation(
                    x=timestamps[len(timestamps)//2],
                    y=max(highs) * 0.95,
                    text=f"<b>🎯 {analysis['selected_pattern']}</b><br><span style='font-size:10px'>{analysis['signal']} - {analysis['trading_recommendation']}</span>",
                    showarrow=False,
                    bgcolor=colors['surface'],
                    bordercolor=signal_color,
                    borderwidth=2,
                    font=dict(size=10, color=colors['text_primary']),
                    row=row, col=col
                )
        
        # Update layout for professional appearance
        fig.update_layout(
            title={
                'text': '<b>🚀 LUNA/USD Multi-Timeframe Analysis</b><br><span style="font-size:14px">Comprehensive Technical Analysis Across All Timeframes</span>',
                'x': 0.5,
                'xanchor': 'center',
                'font': {'size': 18, 'color': colors['text_primary']}
            },
            plot_bgcolor=colors['surface'],
            paper_bgcolor=colors['background'],
            font=dict(color=colors['text_primary'], size=12),
            height=1200,
            showlegend=False,
            hovermode='x unified'
        )
        
        # Update axes for all subplots
        for i in range(1, 3):
            for j in range(1, 3):
                fig.update_xaxes(
                    title_text="<b>Time</b>",
                    title_font=dict(size=12, color=colors['text_primary']),
                    gridcolor=colors['grid'],
                    tickfont=dict(size=10, color=colors['text_secondary']),
                    mirror=True,
                    showgrid=True,
                    row=i, col=j
                )
                fig.update_yaxes(
                    title_text="<b>Price (USD)</b>",
                    title_font=dict(size=12, color=colors['text_primary']),
                    gridcolor=colors['grid'],
                    tickfont=dict(size=10, color=colors['text_secondary']),
                    mirror=True,
                    showgrid=True,
                    row=i, col=j
                )
        
        # Generate timestamp for filename
        timestamp_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"luna_multi_timeframe_{timestamp_str}.png"
        
        # Convert to image
        img_bytes = fig.to_image(format="png", width=1920, height=1200, scale=3)
        
        # Upload to Supabase
        public_url = upload_to_supabase_s3(img_bytes, filename)
        
        print(f"✅ Combined multi-timeframe chart created: {filename}")
        return public_url
        
    except Exception as e:
        print(f"❌ Error creating combined chart: {e}")
        return None

def generate_comprehensive_analysis(timeframe_results, all_llm_analyses):
    """Generate comprehensive analysis combining all timeframes"""
    try:
        # Count signals across timeframes
        bullish_count = 0
        bearish_count = 0
        neutral_count = 0
        
        for tf_data in timeframe_results.values():
            if tf_data['analysis']:
                signal = tf_data['analysis']['signal']
                if signal == 'Bullish':
                    bullish_count += 1
                elif signal == 'Bearish':
                    bearish_count += 1
                else:
                    neutral_count += 1
        
        # Determine overall sentiment
        total_signals = bullish_count + bearish_count + neutral_count
        if total_signals == 0:
            overall_sentiment = "Neutral"
        elif bullish_count > bearish_count:
            overall_sentiment = "Bullish"
        elif bearish_count > bullish_count:
            overall_sentiment = "Bearish"
        else:
            overall_sentiment = "Neutral"
        
        # Get the most significant pattern (highest confidence)
        significant_patterns = []
        for tf_data in timeframe_results.values():
            if tf_data['analysis'] and tf_data['analysis']['confidence'] == 'High':
                significant_patterns.append(tf_data['analysis'])
        
        if not significant_patterns:
            for tf_data in timeframe_results.values():
                if tf_data['analysis'] and tf_data['analysis']['confidence'] == 'Medium':
                    significant_patterns.append(tf_data['analysis'])
        
        main_pattern = significant_patterns[0] if significant_patterns else None
        
        # Generate comprehensive recommendation
        if overall_sentiment == "Bullish":
            recommendation = "Strong Buy"
            reasoning = "Multiple timeframes show bullish patterns, indicating strong upward momentum"
        elif overall_sentiment == "Bearish":
            recommendation = "Sell"
            reasoning = "Multiple timeframes show bearish patterns, indicating potential downward pressure"
        else:
            recommendation = "Hold"
            reasoning = "Mixed signals across timeframes, wait for clearer direction"
        
        # Create tweet summary
        if main_pattern:
            tweet_summary = f"🎯 {main_pattern['selected_pattern']} detected across multiple timeframes! {overall_sentiment} sentiment - {recommendation} recommendation for LUNA/USD"
        else:
            tweet_summary = f"📊 Multi-timeframe analysis shows {overall_sentiment} sentiment for LUNA/USD - {recommendation} recommendation"
        
        return {
            "overall_sentiment": overall_sentiment,
            "overall_recommendation": recommendation,
            "reasoning": reasoning,
            "tweet_summary": tweet_summary,
            "signal_distribution": {
                "bullish": bullish_count,
                "bearish": bearish_count,
                "neutral": neutral_count,
                "total": total_signals
            },
            "main_pattern": main_pattern['selected_pattern'] if main_pattern else "None",
            "main_pattern_confidence": main_pattern['confidence'] if main_pattern else "Low",
            "timeframes_analyzed": len(timeframe_results)
        }
        
    except Exception as e:
        print(f"❌ Error generating comprehensive analysis: {e}")
        return {
            "overall_sentiment": "Neutral",
            "overall_recommendation": "Hold",
            "reasoning": "Analysis error occurred",
            "tweet_summary": "Multi-timeframe analysis completed with mixed signals",
            "signal_distribution": {"bullish": 0, "bearish": 0, "neutral": 0, "total": 0},
            "main_pattern": "None",
            "main_pattern_confidence": "Low",
            "timeframes_analyzed": 0
        }

def upload_to_supabase_s3(file_data: bytes, filename: str, bucket_name: str = "Luna-Twitter"):
    """Upload file to Supabase S3 bucket"""
    try:
        supabase = get_supabase_client()
        
        # Upload to Supabase Storage
        result = supabase.storage.from_(bucket_name).upload(
            path=filename,
            file=file_data,
            file_options={"content-type": "image/png"}
        )
        
        print(f"✅ Successfully uploaded {filename} to {bucket_name} bucket")
        
        # Try to get public URL first
        try:
            public_url = supabase.storage.from_(bucket_name).get_public_url(filename)
            print(f"🌐 Public URL: {public_url}")
            return public_url
        except Exception as e:
            print(f"⚠️ Public URL not available (bucket might be private): {e}")
            
            # Generate signed URL as fallback
            try:
                signed_url = supabase.storage.from_(bucket_name).create_signed_url(filename, 3600)  # 1 hour expiry
                print(f"🔐 Signed URL (expires in 1 hour): {signed_url}")
                return signed_url
            except Exception as e2:
                print(f"❌ Could not generate signed URL: {e2}")
                return None
        
    except Exception as e:
        print(f"❌ Error uploading to Supabase: {e}")
        return None

def create_plotly_candlestick(days=1):
    """Create candlestick chart using Plotly and auto-save to S3"""
    
    # Fetch data
    print(f"📊 Fetching LUNA data for {days} days...")
    raw_data = fetch_luna_data(days)
    
    if not raw_data:
        print("❌ No data available")
        return None
    
    print(f"✅ Got {len(raw_data)} data points")
    
    # Process data
    timestamps = []
    opens = []
    highs = []
    lows = []
    closes = []
    volumes = []
    
    for item in raw_data:
        if len(item) == 5:
            timestamp = datetime.datetime.fromtimestamp(item[0] / 1000)
            timestamps.append(timestamp)
            opens.append(item[1])
            highs.append(item[2])
            lows.append(item[3])
            closes.append(item[4])
            
            # Calculate volume
            volume = abs(item[2] - item[3]) * 1000000
            volumes.append(volume)
    
    print(f"✅ Processed {len(timestamps)} OHLC points")
    
    # Calculate technical indicators
    print("📈 Calculating technical indicators...")
    ma_data = calculate_moving_averages(closes, [20, 50])
    rsi_values = calculate_rsi(closes, 14)
    trend_lines = detect_trend_lines(timestamps, highs, lows, closes)
    patterns = detect_advanced_patterns(timestamps, highs, lows, closes, volumes)
    
    print(f"✅ Technical analysis complete - Found {len(trend_lines)} trend lines, {len(patterns)} patterns")
    
    # LLM-powered pattern analysis
    print("🧠 Analyzing patterns with LLM...")
    market_data = {
        'current_price': closes[-1],
        'price_change_percent': ((closes[-1] - closes[0]) / closes[0] * 100),
        'rsi': rsi_values[-1] if rsi_values[-1] is not None else 50,
        'rsi_signal': "Overbought" if rsi_values[-1] > 70 else "Oversold" if rsi_values[-1] < 30 else "Neutral",
        'ma20': ma_data.get('MA20', [None])[-1] if 'MA20' in ma_data and ma_data['MA20'][-1] is not None else None,
        'trend': "Bullish" if ma_data.get('MA20', [None])[-1] and ma_data.get('MA50', [None])[-1] and ma_data['MA20'][-1] > ma_data['MA50'][-1] else "Bearish" if ma_data.get('MA20', [None])[-1] and ma_data.get('MA50', [None])[-1] and ma_data['MA20'][-1] < ma_data['MA50'][-1] else "Neutral",
        'time_range': f"{timestamps[0].strftime('%Y-%m-%d %H:%M')} to {timestamps[-1].strftime('%Y-%m-%d %H:%M')}"
    }
    
    context = f"LUNA/USD {days}-day analysis with {len(patterns)} patterns detected"
    
    # Try LLM analysis first, fallback to mathematical
    llm_analysis = analyze_patterns_with_llm(patterns, market_data, context)
    
    if llm_analysis:
        print(f"✅ LLM Analysis successful: {llm_analysis['selected_pattern']}")
        pattern_analysis = llm_analysis
    else:
        print("⚠️ Using mathematical fallback for pattern selection")
        pattern_analysis = select_best_pattern_mathematical(patterns)
    
    # Professional color scheme
    colors = {
        'bullish': '#00D4AA',
        'bearish': '#FF6B6B', 
        'neutral': '#8B5CF6',
        'background': '#0F0F23',
        'surface': '#1A1A2E',
        'text_primary': '#FFFFFF',
        'text_secondary': '#A0A0A0',
        'grid': '#2D2D44',
        'accent': '#00D4AA'
    }
    
    # Create subplots with RSI panel
    fig = make_subplots(
        rows=3, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.05,
        subplot_titles=('LUNA/USD Price', 'Volume', 'RSI'),
        row_heights=[0.5, 0.2, 0.3]
    )
    
    # Add professional candlestick chart
    fig.add_trace(
        go.Candlestick(
            x=timestamps,
            open=opens,
            high=highs,
            low=lows,
            close=closes,
            name="LUNA/USD",
            increasing_line_color=colors['bullish'],
            decreasing_line_color=colors['bearish'],
            increasing_fillcolor=colors['bullish'],
            decreasing_fillcolor=colors['bearish'],
            line=dict(width=1.5),
            whiskerwidth=0.8
        ),
        row=1, col=1
    )
    
    # Add professional moving averages
    ma_colors = {
        'MA20': '#FFA500',
        'MA50': '#FFD700'
    }
    
    for ma_name, ma_values in ma_data.items():
        fig.add_trace(
            go.Scatter(
                x=timestamps,
                y=ma_values,
                name=ma_name,
                line=dict(
                    color=ma_colors.get(ma_name, colors['neutral']), 
                    width=2.5,
                    dash='solid'
                ),
                opacity=0.9,
                hovertemplate=f"<b>{ma_name}</b><br>" +
                             "Time: %{x}<br>" +
                             "Price: $%{y:.4f}<br>" +
                             "<extra></extra>"
            ),
            row=1, col=1
        )
    
    # Add professional trend lines
    trend_colors = {
        'support': '#4ECDC4',
        'resistance': '#FF6B6B'
    }
    
    for trend_line in trend_lines:
        fig.add_trace(
            go.Scatter(
                x=trend_line['x'],
                y=trend_line['y'],
                mode='lines',
                name=f"{trend_line['type'].title()} Line",
                line=dict(
                    color=trend_colors.get(trend_line['type'], colors['neutral']), 
                    dash='dash', 
                    width=2.5
                ),
                opacity=0.8,
                hovertemplate=f"<b>{trend_line['type'].title()} Line</b><br>" +
                             "Time: %{x}<br>" +
                             "Price: $%{y:.4f}<br>" +
                             "<extra></extra>"
            ),
            row=1, col=1
        )
    
    # Add professional volume bars
    volume_colors = [colors['bullish'] if closes[i] >= opens[i] else colors['bearish'] for i in range(len(closes))]
    
    fig.add_trace(
        go.Bar(
            x=timestamps,
            y=volumes,
            name="Volume",
            marker_color=volume_colors,
            opacity=0.8,
            hovertemplate="<b>Volume</b><br>" +
                         "Time: %{x}<br>" +
                         "Volume: %{y:,.0f}<br>" +
                         "<extra></extra>"
        ),
        row=2, col=1
    )
    
    # Add professional RSI with gradient fill
    fig.add_trace(
        go.Scatter(
            x=timestamps,
            y=rsi_values,
            name="RSI",
            line=dict(color=colors['neutral'], width=2.5),
            fill='tonexty',
            fillcolor=f'rgba(139, 92, 246, 0.2)',
            hovertemplate="<b>RSI</b><br>" +
                         "Time: %{x}<br>" +
                         "RSI: %{y:.1f}<br>" +
                         "<extra></extra>"
        ),
        row=3, col=1
    )
    
    # Add professional RSI zones and levels
    # Overbought zone (70-100)
    fig.add_hrect(y0=70, y1=100, fillcolor="rgba(255, 107, 107, 0.1)", layer="below", row=3, col=1)
    fig.add_hline(y=70, line_dash="dash", line_color=colors['bearish'], opacity=0.8, line_width=2, row=3, col=1)
    
    # Oversold zone (0-30)
    fig.add_hrect(y0=0, y1=30, fillcolor="rgba(0, 212, 170, 0.1)", layer="below", row=3, col=1)
    fig.add_hline(y=30, line_dash="dash", line_color=colors['bullish'], opacity=0.8, line_width=2, row=3, col=1)
    
    # Neutral zone center line
    fig.add_hline(y=50, line_dash="dot", line_color=colors['text_secondary'], opacity=0.6, line_width=1, row=3, col=1)
    
    # Calculate additional professional metrics
    price_change = closes[-1] - closes[0]
    price_change_percent = (price_change / closes[0]) * 100
    high_24h = max(highs)
    low_24h = min(lows)
    volume_24h = sum(volumes)
    
    # Create title with proper color coding
    price_color = colors['bullish'] if price_change >= 0 else colors['bearish']
    title_text = f"<b>LUNA/USD</b> {days}d Chart • <span style='color:{price_color}'>${closes[-1]:.4f}</span> <span style='color:{price_color}'>({price_change_percent:+.2f}%)</span>"
    
    # Update layout with professional styling
    fig.update_layout(
        title={
            'text': title_text,
            'x': 0.5,
            'font': {'size': 18, 'color': colors['text_primary'], 'family': 'Arial, sans-serif'},
            'xanchor': 'center'
        },
        template='plotly_dark',
        paper_bgcolor=colors['background'],
        plot_bgcolor=colors['surface'],
        font=dict(
            color=colors['text_primary'],
            family='Arial, sans-serif',
            size=12
        ),
        height=900,  # Increased height for professional look
        showlegend=True,
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1,
            bgcolor=colors['surface'],
            bordercolor=colors['grid'],
            borderwidth=1,
            font=dict(size=11, color=colors['text_primary'])
        ),
        xaxis_rangeslider_visible=False,
        margin=dict(l=60, r=60, t=80, b=60),
        hovermode='x unified',
        hoverlabel=dict(
            bgcolor=colors['surface'],
            bordercolor=colors['accent'],
            font_size=12,
            font_family="Arial, sans-serif"
        )
    )
    
    # Update axes with professional styling
    fig.update_xaxes(
        title_text="<b>Time</b>",
        showgrid=True,
        gridcolor=colors['grid'],
        color=colors['text_primary'],
        title_font=dict(size=12, color=colors['text_primary']),
        tickfont=dict(size=10, color=colors['text_secondary']),
        linecolor=colors['grid'],
        mirror=True
    )
    
    fig.update_yaxes(
        title_text="<b>Price (USD)</b>",
        showgrid=True,
        gridcolor=colors['grid'],
        color=colors['text_primary'],
        title_font=dict(size=12, color=colors['text_primary']),
        tickfont=dict(size=10, color=colors['text_secondary']),
        linecolor=colors['grid'],
        mirror=True,
        row=1, col=1
    )
    
    fig.update_yaxes(
        title_text="<b>Volume</b>",
        showgrid=True,
        gridcolor=colors['grid'],
        color=colors['text_primary'],
        title_font=dict(size=12, color=colors['text_primary']),
        tickfont=dict(size=10, color=colors['text_secondary']),
        linecolor=colors['grid'],
        mirror=True,
        row=2, col=1
    )
    
    fig.update_yaxes(
        title_text="<b>RSI</b>",
        showgrid=True,
        gridcolor=colors['grid'],
        color=colors['text_primary'],
        title_font=dict(size=12, color=colors['text_primary']),
        tickfont=dict(size=10, color=colors['text_secondary']),
        linecolor=colors['grid'],
        mirror=True,
        range=[0, 100],
        row=3, col=1
    )
    
    # Add professional annotations
    # Current price annotation
    fig.add_annotation(
        x=timestamps[-1],
        y=closes[-1],
        text=f"<b>${closes[-1]:.4f}</b>",
        showarrow=True,
        arrowhead=2,
        arrowsize=1,
        arrowwidth=2,
        arrowcolor=colors['accent'],
        ax=20,
        ay=-30,
        bgcolor=colors['surface'],
        bordercolor=colors['accent'],
        borderwidth=1,
        font=dict(size=12, color=colors['text_primary']),
        row=1, col=1
    )
    
    # High/Low annotations
    high_idx = highs.index(high_24h)
    low_idx = lows.index(low_24h)
    
    fig.add_annotation(
        x=timestamps[high_idx],
        y=high_24h,
        text=f"<b>24H High<br>${high_24h:.4f}</b>",
        showarrow=True,
        arrowhead=2,
        arrowsize=1,
        arrowwidth=2,
        arrowcolor=colors['bullish'],
        ax=0,
        ay=-40,
        bgcolor=colors['surface'],
        bordercolor=colors['bullish'],
        borderwidth=1,
        font=dict(size=10, color=colors['text_primary']),
        row=1, col=1
    )
    
    fig.add_annotation(
        x=timestamps[low_idx],
        y=low_24h,
        text=f"<b>24H Low<br>${low_24h:.4f}</b>",
        showarrow=True,
        arrowhead=2,
        arrowsize=1,
        arrowwidth=2,
        arrowcolor=colors['bearish'],
        ax=0,
        ay=40,
        bgcolor=colors['surface'],
        bordercolor=colors['bearish'],
        borderwidth=1,
        font=dict(size=10, color=colors['text_primary']),
        row=1, col=1
    )
    
    # Add RSI signal annotation
    current_rsi = rsi_values[-1] if rsi_values[-1] is not None else 50
    rsi_signal = "Overbought" if current_rsi > 70 else "Oversold" if current_rsi < 30 else "Neutral"
    rsi_color = colors['bearish'] if current_rsi > 70 else colors['bullish'] if current_rsi < 30 else colors['neutral']
    
    fig.add_annotation(
        x=timestamps[-1],
        y=current_rsi,
        text=f"<b>RSI: {current_rsi:.1f}<br>{rsi_signal}</b>",
        showarrow=True,
        arrowhead=2,
        arrowsize=1,
        arrowwidth=2,
        arrowcolor=rsi_color,
        ax=20,
        ay=-20,
        bgcolor=colors['surface'],
        bordercolor=rsi_color,
        borderwidth=1,
        font=dict(size=10, color=colors['text_primary']),
        row=3, col=1
    )
    
    # Add LLM-powered pattern annotations to the chart
    if pattern_analysis:
        pattern_type = pattern_analysis['selected_pattern']
        pattern_signal = pattern_analysis['signal']
        pattern_recommendation = pattern_analysis['trading_recommendation']
        
        # Color based on signal
        signal_color = colors['bullish'] if pattern_signal == 'Bullish' else colors['bearish'] if pattern_signal == 'Bearish' else colors['neutral']
        
        # Add main pattern annotation
        fig.add_annotation(
            x=timestamps[len(timestamps)//2],
            y=max(highs) * 0.98,
            text=f"<b>🎯 {pattern_type}</b><br><span style='font-size:10px'>{pattern_signal} Signal - {pattern_recommendation}</span>",
            showarrow=True,
            arrowhead=2,
            arrowsize=1,
            arrowwidth=2,
            arrowcolor=signal_color,
            ax=0,
            ay=-40,
            bgcolor=colors['surface'],
            bordercolor=signal_color,
            borderwidth=2,
            font=dict(size=12, color=colors['text_primary']),
            row=1, col=1
        )
        
        # Add LLM analysis annotation
        fig.add_annotation(
            x=timestamps[-1],
            y=max(highs) * 0.95,
            text=f"<b>🧠 LUNA Analysis</b><br><span style='font-size:10px'>{len(patterns)} patterns analyzed</span>",
            showarrow=False,
            bgcolor=colors['surface'],
            bordercolor=colors['accent'],
            borderwidth=1,
            font=dict(size=10, color=colors['text_primary']),
            row=1, col=1
        )
    
    # Generate timestamp for filename
    timestamp_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"luna_chart_{days}d_{timestamp_str}.png"
    
    # Convert to high-quality PNG bytes
    print("🖼️ Generating professional chart image...")
    img_bytes = fig.to_image(
        format="png", 
        width=1920,  # Higher resolution
        height=1080,  # 16:9 aspect ratio
        scale=3,  # Higher scale for crisp text
        engine="kaleido"
    )
    
    # Upload to Supabase S3
    print(f"☁️ Uploading {filename} to Supabase S3...")
    public_url = upload_to_supabase_s3(img_bytes, filename)
    
    if public_url:
        print(f"🎉 Chart successfully uploaded!")
        
        # Calculate current RSI
        current_rsi = float(rsi_values[-1]) if rsi_values[-1] is not None else 0.0
        
        # Get current moving average values
        current_ma20 = float(ma_data.get('MA20', [None])[-1]) if 'MA20' in ma_data and ma_data['MA20'][-1] is not None else None
        current_ma50 = float(ma_data.get('MA50', [None])[-1]) if 'MA50' in ma_data and ma_data['MA50'][-1] is not None else None
        
        return {
            "success": True,
            "filename": filename,
            "public_url": public_url,
            "chart_data": {
                "current_price": closes[-1],
                "price_change": closes[-1] - closes[0],
                "price_change_percent": ((closes[-1] - closes[0]) / closes[0] * 100),
                "data_points": len(timestamps),
                "time_range": f"{timestamps[0].strftime('%Y-%m-%d %H:%M')} to {timestamps[-1].strftime('%Y-%m-%d %H:%M')}"
            },
            "technical_analysis": {
                "rsi": {
                    "current": current_rsi,
                    "signal": "Overbought" if current_rsi > 70 else "Oversold" if current_rsi < 30 else "Neutral"
                },
                "moving_averages": {
                    "ma20": current_ma20,
                    "ma50": current_ma50,
                    "trend": "Bullish" if current_ma20 and current_ma50 and current_ma20 > current_ma50 else "Bearish" if current_ma20 and current_ma50 and current_ma20 < current_ma50 else "Neutral"
                },
                "trend_lines": {
                    "count": len(trend_lines),
                    "types": [line['type'] for line in trend_lines]
                },
                "patterns": [{
                    'type': p['type'],
                    'description': p['description'],
                    'confidence': p['confidence']
                } for p in patterns],
                "pattern_summary": {
                    "total_patterns": len(patterns),
                    "pattern_types": list(set([p['type'] for p in patterns])),
                    "high_confidence": len([p for p in patterns if p.get('confidence') == 'High']),
                    "medium_confidence": len([p for p in patterns if p.get('confidence') == 'Medium']),
                    "main_pattern": patterns[0]['type'] if patterns else None,
                    "main_pattern_description": patterns[0]['description'] if patterns else None
                },
                "llm_analysis": pattern_analysis,
                "support_levels": [line['y'][-1] for line in trend_lines if line['type'] == 'support'],
                "resistance_levels": [line['y'][-1] for line in trend_lines if line['type'] == 'resistance']
            }
        }
    else:
        print("❌ Failed to upload to Supabase")
        return {
            "success": False,
            "error": "Failed to upload to Supabase S3"
        }

@app.route('/')
def home():
    """Home endpoint with API documentation"""
    return jsonify({
        "service": "LUNA Chart Generator",
        "version": "1.0.0",
        "endpoints": {
            "/": "This documentation",
            "/generate": "Generate and upload LUNA chart (GET or POST)",
            "/tweet": "Generate tweet-ready data with LLM analysis (GET or POST)",
            "/multi": "Generate comprehensive multi-timeframe analysis with all 4 charts in one image (GET or POST)",
            "/health": "Health check endpoint"
        },
        "parameters": {
            "days": "Number of days for chart data (1, 7, 14, 30, 90, 180, 365, max)"
        },
        "example": "/generate?days=1"
    })

@app.route('/health')
def health():
    """Health check endpoint"""
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.datetime.now().isoformat(),
        "service": "LUNA Chart Generator"
    })

@app.route('/multi', methods=['GET', 'POST'])
def generate_multi_timeframe_analysis():
    """Generate comprehensive multi-timeframe analysis with all 4 charts in one image"""
    try:
        print("🚀 Starting multi-timeframe analysis...")
        
        # Define timeframes to analyze
        timeframes = [1, 30, 90, 365]
        timeframe_names = ['1D', '30D', '90D', '365D']
        
        # Store results for each timeframe
        timeframe_results = {}
        all_patterns = []
        all_llm_analyses = []
        
        # Analyze each timeframe
        for i, days in enumerate(timeframes):
            print(f"📊 Analyzing {timeframe_names[i]} timeframe...")
            
            try:
                # Get data for this timeframe
                raw_data = fetch_luna_data(days)
                if not raw_data:
                    print(f"⚠️ No data for {days} days")
                    continue
                
                print(f"✅ Got {len(raw_data)} data points for {timeframe_names[i]}")
                
                # Process data (same as in create_plotly_candlestick)
                timestamps = []
                opens = []
                highs = []
                lows = []
                closes = []
                volumes = []
                
                for candle in raw_data:
                    timestamps.append(datetime.datetime.fromtimestamp(candle[0]/1000))
                    opens.append(candle[1])
                    highs.append(candle[2])
                    lows.append(candle[3])
                    closes.append(candle[4])
                    volumes.append(1000000)  # Placeholder volume
                
                # Calculate technical indicators
                ma_data = calculate_moving_averages(closes, [20, 50])
                rsi_values = calculate_rsi(closes, 14)
                trend_lines = detect_trend_lines(timestamps, highs, lows, closes)
                patterns = detect_advanced_patterns(timestamps, highs, lows, closes, volumes)
                
                # Prepare market data for LLM
                market_data = {
                    'current_price': closes[-1],
                    'price_change_percent': ((closes[-1] - closes[0]) / closes[0] * 100),
                    'rsi': rsi_values[-1] if rsi_values[-1] is not None else 50,
                    'rsi_signal': "Overbought" if rsi_values[-1] > 70 else "Oversold" if rsi_values[-1] < 30 else "Neutral",
                    'ma20': ma_data.get('MA20', [None])[-1] if 'MA20' in ma_data and ma_data['MA20'][-1] is not None else None,
                    'trend': "Bullish" if ma_data.get('MA20', [None])[-1] and ma_data.get('MA50', [None])[-1] and ma_data['MA20'][-1] > ma_data['MA50'][-1] else "Bearish" if ma_data.get('MA20', [None])[-1] and ma_data.get('MA50', [None])[-1] and ma_data['MA20'][-1] < ma_data['MA50'][-1] else "Neutral",
                    'time_range': f"{timestamps[0].strftime('%Y-%m-%d')} to {timestamps[-1].strftime('%Y-%m-%d')}"
                }
                
                context = f"LUNA/USD {days}-day analysis with {len(patterns)} patterns detected"
                
                # Try LLM analysis first, fallback to mathematical
                llm_analysis = analyze_patterns_with_llm(patterns, market_data, context)
                
                if llm_analysis:
                    pattern_analysis = llm_analysis
                else:
                    pattern_analysis = select_best_pattern_mathematical(patterns)
                
                # Store results
                timeframe_results[timeframe_names[i]] = {
                    'days': days,
                    'data': {
                        'timestamps': timestamps,
                        'highs': highs,
                        'lows': lows,
                        'closes': closes,
                        'volumes': volumes
                    },
                    'technical': {
                        'ma_data': ma_data,
                        'rsi_values': rsi_values,
                        'trend_lines': trend_lines,
                        'patterns': patterns
                    },
                    'analysis': pattern_analysis,
                    'market_data': market_data
                }
                
                all_patterns.extend(patterns)
                if pattern_analysis:
                    all_llm_analyses.append(pattern_analysis)
                
                print(f"✅ {timeframe_names[i]} analysis complete - {len(patterns)} patterns, {pattern_analysis['signal'] if pattern_analysis else 'No signal'}")
                
            except Exception as e:
                print(f"❌ Error analyzing {timeframe_names[i]}: {e}")
                continue
        
        if not timeframe_results:
            return jsonify({
                "success": False,
                "error": "No data available for any timeframe"
            }), 500
        
        # Create combined chart with all 4 timeframes
        print("🎨 Creating combined multi-timeframe chart...")
        combined_chart_url = create_combined_multi_timeframe_chart(timeframe_results)
        
        # Generate comprehensive analysis
        comprehensive_analysis = generate_comprehensive_analysis(timeframe_results, all_llm_analyses)
        
        # Prepare final response
        response_data = {
            "success": True,
            "public_url": combined_chart_url,
            "timeframes_analyzed": list(timeframe_results.keys()),
            "comprehensive_analysis": comprehensive_analysis,
            "individual_timeframes": {
                tf: {
                    "pattern": data['analysis']['selected_pattern'] if data['analysis'] else "None",
                    "signal": data['analysis']['signal'] if data['analysis'] else "Neutral",
                    "recommendation": data['analysis']['trading_recommendation'] if data['analysis'] else "Hold",
                    "confidence": data['analysis']['confidence'] if data['analysis'] else "Low",
                    "price_change": f"{data['market_data']['price_change_percent']:+.2f}%",
                    "rsi": data['market_data']['rsi'],
                    "rsi_signal": data['market_data']['rsi_signal'],
                    "total_patterns": len(data['technical']['patterns'])
                }
                for tf, data in timeframe_results.items()
            },
            "total_patterns_detected": len(all_patterns),
            "bullish_timeframes": len([tf for tf, data in timeframe_results.items() if data['analysis'] and data['analysis']['signal'] == 'Bullish']),
            "bearish_timeframes": len([tf for tf, data in timeframe_results.items() if data['analysis'] and data['analysis']['signal'] == 'Bearish'])
        }
        
        print(f"✅ Multi-timeframe analysis complete - {len(timeframe_results)} timeframes analyzed")
        return jsonify(response_data)
        
    except Exception as e:
        print(f"Error in generate_multi_timeframe_analysis: {e}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

@app.route('/tweet', methods=['GET', 'POST'])
def generate_tweet_data():
    """Generate tweet-ready data with LLM analysis"""
    try:
        # Get days parameter
        if request.method == 'POST':
            data = request.get_json() or {}
            days = data.get('days', 1)
        else:
            days = request.args.get('days', 1, type=int)
        
        # Validate days parameter
        valid_days = [1, 7, 14, 30, 90, 180, 365, 'max']
        if days not in valid_days:
            return jsonify({
                "success": False,
                "error": f"Invalid days parameter. Must be one of: {valid_days}"
            }), 400
        
        # Generate chart and get analysis
        result = create_plotly_candlestick(days)
        
        if result and result.get("success"):
            # Extract tweet-ready data
            chart_data = result.get("chart_data", {})
            llm_analysis = result.get("technical_analysis", {}).get("llm_analysis", {})
            
            tweet_data = {
                "success": True,
                "public_url": result.get("public_url"),
                "pattern": llm_analysis.get("selected_pattern", "Unknown"),
                "signal": llm_analysis.get("signal", "Neutral"),
                "recommendation": llm_analysis.get("trading_recommendation", "Hold"),
                "confidence": llm_analysis.get("confidence", "Medium"),
                "current_price": f"${chart_data.get('current_price', 0):.6f}",
                "price_change": f"{chart_data.get('price_change_percent', 0):+.2f}%",
                "tweet_summary": llm_analysis.get("tweet_summary", "LUNA analysis complete"),
                "reasoning": llm_analysis.get("reasoning", "Pattern analysis completed"),
                "rsi": result.get("technical_analysis", {}).get("rsi", {}).get("current", 0),
                "rsi_signal": result.get("technical_analysis", {}).get("rsi", {}).get("signal", "Neutral"),
                "total_patterns": result.get("technical_analysis", {}).get("pattern_summary", {}).get("total_patterns", 0)
            }
            
            return jsonify(tweet_data)
        else:
            return jsonify({
                "success": False,
                "error": result.get("error", "Unknown error occurred")
            }), 500
            
    except Exception as e:
        print(f"Error in generate_tweet_data: {e}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

@app.route('/generate', methods=['GET', 'POST'])
def generate_chart():
    """Generate LUNA candlestick chart and upload to Supabase S3"""
    try:
        # Get days parameter
        if request.method == 'POST':
            data = request.get_json() or {}
            days = data.get('days', 1)
        else:
            days = request.args.get('days', 1, type=int)
        
        # Validate days parameter
        valid_days = [1, 7, 14, 30, 90, 180, 365, 'max']
        if days not in valid_days:
            return jsonify({
                "success": False,
                "error": f"Invalid days parameter. Must be one of: {valid_days}"
            }), 400
        
        # Generate chart
        result = create_plotly_candlestick(days)
        
        if result and result.get("success"):
            return jsonify(result)
        else:
            return jsonify({
                "success": False,
                "error": result.get("error", "Unknown error occurred")
            }), 500
            
    except Exception as e:
        print(f"Error in generate_chart: {e}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
