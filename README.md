# LUNA Chart Generator - Professional Trading Analysis Tool

A world-class Flask web service that generates professional-grade LUNA candlestick charts with advanced technical analysis, LLM-powered pattern recognition, and multi-timeframe analysis capabilities.

## 🚀 Features

### 📊 **Professional Chart Generation**
- High-resolution candlestick charts using Plotly
- Auto-uploads to Supabase S3 bucket
- Multiple timeframes (1d, 7d, 14d, 30d, 90d, 180d, 365d, max)
- Professional dark theme with custom color schemes

### 🧠 **Advanced Technical Analysis**
- **Trend Lines**: Automatic support/resistance detection
- **Moving Averages**: MA20, MA50 with trend analysis
- **RSI Indicator**: Momentum analysis with overbought/oversold zones
- **Volume Analysis**: Trading volume patterns and spikes
- **Pattern Recognition**: 15+ chart patterns including:
  - Head and Shoulders (Bullish/Bearish)
  - Double Top/Bottom
  - Cup and Handle
  - Rising/Falling Wedges
  - Ascending/Descending Triangles

### 🤖 **LLM-Powered Intelligence**
- **ChatGPT Integration**: Intelligent pattern selection and analysis
- **Mathematical Fallback**: Robust analysis when LLM unavailable
- **Smart Recommendations**: Buy/Sell/Hold signals with confidence levels
- **Tweet-Ready Output**: Social media optimized summaries

### 📈 **Multi-Timeframe Analysis**
- **Comprehensive View**: All 4 timeframes in one professional chart
- **Signal Aggregation**: Combined analysis across timeframes
- **Professional Layout**: 2x2 grid with consistent styling
- **Complete Analysis**: Individual and comprehensive recommendations

### 🎨 **Professional Styling**
- Premium dark theme (#0F0F23 background, #1A1A2E surface)
- High-resolution output (1920x1080, 3x scale)
- Professional annotations and price markers
- RSI zones with gradient fills
- Enhanced typography and spacing
- Interactive hover tooltips

## 🌐 API Endpoints

### `GET /`
Returns API documentation and available endpoints.

### `GET /health`
Health check endpoint.

### `GET /generate?days=1`
Generate and upload a professional LUNA chart with advanced technical analysis.

**Parameters:**
- `days` (optional): Number of days for chart data. Valid values: 1, 7, 14, 30, 90, 180, 365, max. Default: 1

### `GET /tweet?days=1`
Generate tweet-ready data with LLM analysis for social media.

**Parameters:**
- `days` (optional): Number of days for analysis. Valid values: 1, 7, 14, 30, 90, 180, 365, max. Default: 1

### `GET /multi`
Generate comprehensive multi-timeframe analysis with all 4 charts in one professional image.

**Features:**
- Analyzes 1D, 30D, 90D, and 365D timeframes simultaneously
- Creates combined chart with 2x2 grid layout
- Provides comprehensive analysis across all timeframes
- Generates overall sentiment and recommendations

**Response Examples:**

#### `/generate` Response:
```json
{
  "success": true,
  "public_url": "https://your-project.supabase.co/storage/v1/object/public/Luna-Twitter/luna_chart_1d_20250109_143022.png",
  "chart_data": {
    "current_price": 0.013882,
    "price_change_percent": -2.24,
    "data_points": 48,
    "time_range": "2025-01-09 00:00 to 2025-01-09 23:59"
  },
  "technical_analysis": {
    "rsi": {
      "current": 54.6,
      "signal": "Neutral"
    },
    "moving_averages": {
      "ma20": 0.0132,
      "ma50": 0.0131,
      "trend": "Bullish"
    },
    "trend_lines": {
      "count": 2,
      "types": ["support", "resistance"]
    },
    "patterns": [
      {
        "type": "Head and Shoulders",
        "description": "Classic bearish reversal pattern",
        "confidence": "High"
      }
    ],
    "llm_analysis": {
      "selected_pattern": "Head and Shoulders",
      "signal": "Bearish",
      "recommendation": "Sell",
      "confidence": "High",
      "tweet_summary": "Bearish signal detected on LUNA/USD with a high confidence Head and Shoulders pattern."
    }
  }
}
```

#### `/tweet` Response:
```json
{
  "success": true,
  "public_url": "https://your-project.supabase.co/storage/v1/object/public/Luna-Twitter/luna_chart_1d_20250109_143022.png",
  "pattern": "Head and Shoulders",
  "signal": "Bearish",
  "recommendation": "Sell",
  "confidence": "High",
  "current_price": "$0.013882",
  "price_change": "-2.24%",
  "tweet_summary": "Bearish signal detected on LUNA/USD with a high confidence Head and Shoulders pattern. Consider selling for potential downside.",
  "rsi": 54.6,
  "rsi_signal": "Neutral",
  "total_patterns": 72
}
```

#### `/multi` Response:
```json
{
  "success": true,
  "public_url": "https://your-project.supabase.co/storage/v1/object/public/Luna-Twitter/luna_multi_timeframe_20250109_143022.png",
  "timeframes_analyzed": ["1D", "30D", "90D", "365D"],
  "comprehensive_analysis": {
    "overall_sentiment": "Neutral",
    "overall_recommendation": "Hold",
    "reasoning": "Mixed signals across timeframes, wait for clearer direction",
    "tweet_summary": "Multi-timeframe analysis shows Neutral sentiment for LUNA/USD - Hold recommendation",
    "signal_distribution": {
      "bullish": 2,
      "bearish": 2,
      "neutral": 0,
      "total": 4
    },
    "main_pattern": "Head and Shoulders",
    "main_pattern_confidence": "High"
  },
  "individual_timeframes": {
    "1D": {
      "pattern": "Head and Shoulders",
      "signal": "Bearish",
      "recommendation": "Sell",
      "confidence": "High",
      "price_change": "-2.92%",
      "rsi": 52.3,
      "total_patterns": 73
    },
    "90D": {
      "pattern": "Double Bottom",
      "signal": "Bullish",
      "recommendation": "Buy",
      "confidence": "Medium",
      "price_change": "-27.35%",
      "rsi": 43.0,
      "total_patterns": 5
    }
  },
  "total_patterns_detected": 266,
  "bullish_timeframes": 2,
  "bearish_timeframes": 2
}
```

### `POST /generate`, `POST /tweet`, `POST /multi`
Same as GET but accepts JSON payload:
```json
{
  "days": 7
}
```

## 🔧 Environment Variables

Set these in your Railway deployment:

### Required:
- `SUPABASE_URL`: Your Supabase project URL
- `SUPABASE_SERVICE_ROLE_KEY`: Your Supabase service role key
- `SUPABASE_BUCKET_NAME`: Your Supabase storage bucket name (default: "Luna-Twitter")

### Optional (for LLM features):
- `OPENAI_API_KEY`: Your OpenAI API key for ChatGPT integration (optional - uses mathematical fallback if not provided)

## 🚀 Deployment to Railway

1. Push this folder to GitHub
2. Connect your GitHub repo to Railway
3. Set the environment variables in Railway dashboard
4. Deploy!

**Note**: The service uses Python 3.11 and numpy 1.26.4 for optimal compatibility.

## 💡 Usage Examples

### Basic Chart Generation:
```bash
# Generate 1-day chart with full technical analysis
curl https://your-railway-app.railway.app/generate

# Generate 7-day chart
curl https://your-railway-app.railway.app/generate?days=7

# Generate 90-day chart (long-term analysis)
curl https://your-railway-app.railway.app/generate?days=90
```

### Tweet-Ready Data:
```bash
# Get tweet-ready analysis for 1-day
curl https://your-railway-app.railway.app/tweet

# Get tweet-ready analysis for 90-day (bullish patterns)
curl https://your-railway-app.railway.app/tweet?days=90
```

### Multi-Timeframe Analysis:
```bash
# Get comprehensive multi-timeframe analysis
curl https://your-railway-app.railway.app/multi
```

### Health Check:
```bash
# Check service status
curl https://your-railway-app.railway.app/health
```

### JSON Payload Examples:
```bash
# POST request with JSON
curl -X POST https://your-railway-app.railway.app/tweet \
  -H "Content-Type: application/json" \
  -d '{"days": 90}'

# Multi-timeframe analysis
curl -X POST https://your-railway-app.railway.app/multi \
  -H "Content-Type: application/json" \
  -d '{}'
```

## 🛠️ Local Development

```bash
# Clone and navigate to project
git clone <your-repo>
cd railway-deploy

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Set environment variables
cp env.example .env
# Edit .env with your Supabase credentials and optional OpenAI API key

# Run locally
python app.py
```

The service will be available at `http://localhost:5000`

### Local Testing:
```bash
# Test single timeframe
curl http://localhost:5000/generate?days=1

# Test tweet endpoint
curl http://localhost:5000/tweet?days=90

# Test multi-timeframe
curl http://localhost:5000/multi

# Health check
curl http://localhost:5000/health
```

## 🎯 Key Features Summary

| Feature | Description | Endpoint |
|---------|-------------|----------|
| **Professional Charts** | High-resolution candlestick charts with dark theme | `/generate` |
| **Advanced TA** | Trend lines, MAs, RSI, pattern recognition | All endpoints |
| **LLM Analysis** | ChatGPT-powered intelligent pattern selection | All endpoints |
| **Tweet-Ready Data** | Social media optimized analysis and summaries | `/tweet` |
| **Multi-Timeframe** | 4 timeframes in one comprehensive chart | `/multi` |
| **Pattern Detection** | 15+ chart patterns with confidence levels | All endpoints |
| **Professional Styling** | TradingView-quality visual design | All endpoints |

## 🚀 Production Ready

This service is production-ready and includes:
- ✅ **Error handling** and graceful fallbacks
- ✅ **High-resolution output** (1920x1080, 3x scale)
- ✅ **Professional styling** with consistent theming
- ✅ **LLM integration** with mathematical fallback
- ✅ **Multi-timeframe analysis** for comprehensive insights
- ✅ **Tweet-ready output** for social media automation
- ✅ **Railway deployment** with proper configuration
- ✅ **Health monitoring** and status endpoints

**Ready for professional trading analysis and social media automation!** 🎉
