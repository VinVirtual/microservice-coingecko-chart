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
from plotly.subplots import make_subplots
from supabase import create_client, Client
from dotenv import load_dotenv
import base64

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
    
    # Create subplots
    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.1,
        subplot_titles=('LUNA/USD Price', 'Volume'),
        row_heights=[0.7, 0.3]
    )
    
    # Add candlestick chart
    fig.add_trace(
        go.Candlestick(
            x=timestamps,
            open=opens,
            high=highs,
            low=lows,
            close=closes,
            name="LUNA/USD",
            increasing_line_color='#00FF88',
            decreasing_line_color='#FF4444',
            increasing_fillcolor='#00FF88',
            decreasing_fillcolor='#FF4444'
        ),
        row=1, col=1
    )
    
    # Add volume bars
    volume_colors = ['#00FF88' if closes[i] >= opens[i] else '#FF4444' for i in range(len(closes))]
    
    fig.add_trace(
        go.Bar(
            x=timestamps,
            y=volumes,
            name="Volume",
            marker_color=volume_colors,
            opacity=0.7
        ),
        row=2, col=1
    )
    
    # Update layout
    fig.update_layout(
        title={
            'text': f"LUNA/USD {days}d Chart • ${closes[-1]:.4f} ({((closes[-1] - closes[0]) / closes[0] * 100):+.2f}%)",
            'x': 0.5,
            'font': {'size': 16, 'color': 'white'}
        },
        template='plotly_dark',
        paper_bgcolor='#1A1D21',
        plot_bgcolor='#1A1D21',
        font=dict(color='white'),
        height=600,
        showlegend=False,
        xaxis_rangeslider_visible=False
    )
    
    # Update axes
    fig.update_xaxes(
        title_text="Time",
        showgrid=True,
        gridcolor='#2D3748',
        color='white'
    )
    
    fig.update_yaxes(
        title_text="Price (USD)",
        showgrid=True,
        gridcolor='#2D3748',
        color='white',
        row=1, col=1
    )
    
    fig.update_yaxes(
        title_text="Volume",
        showgrid=True,
        gridcolor='#2D3748',
        color='white',
        row=2, col=1
    )
    
    # Generate timestamp for filename
    timestamp_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"luna_chart_{days}d_{timestamp_str}.png"
    
    # Convert to PNG bytes
    print("🖼️ Generating chart image...")
    img_bytes = fig.to_image(format="png", width=1600, height=1000, scale=2)
    
    # Upload to Supabase S3
    print(f"☁️ Uploading {filename} to Supabase S3...")
    public_url = upload_to_supabase_s3(img_bytes, filename)
    
    if public_url:
        print(f"🎉 Chart successfully uploaded!")
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
