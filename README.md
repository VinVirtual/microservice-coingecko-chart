# LUNA Chart Generator - Railway Service

A Flask web service that generates beautiful LUNA candlestick charts and uploads them to Supabase S3.

## Features

- 📊 Generates professional candlestick charts using Plotly
- ☁️ Auto-uploads charts to Supabase S3 bucket
- 🌐 RESTful API endpoints
- 📱 Multiple timeframes (1d, 7d, 14d, 30d, 90d, 180d, 365d, max)
- 🎨 CoinMarketCap-style dark theme
- 📈 **Advanced Technical Analysis:**
  - Automatic trend line detection (support/resistance)
  - Moving averages (MA20, MA50)
  - RSI indicator with overbought/oversold levels
  - Chart pattern recognition (triangles, flags)
  - Volume analysis
- 🎨 **Professional Styling:**
  - Premium dark theme with custom color schemes
  - High-resolution output (1920x1080, 3x scale)
  - Professional annotations and price markers
  - RSI zones with gradient fills
  - Enhanced typography and spacing
  - Interactive hover tooltips

## API Endpoints

### `GET /`
Returns API documentation and available endpoints.

### `GET /health`
Health check endpoint.

### `GET /generate?days=1`
Generate and upload a LUNA chart for the specified number of days.

**Parameters:**
- `days` (optional): Number of days for chart data. Valid values: 1, 7, 14, 30, 90, 180, 365, max. Default: 1

**Response:**
```json
{
  "success": true,
  "filename": "luna_chart_1d_20250109_143022.png",
  "public_url": "https://your-project.supabase.co/storage/v1/object/public/Luna-Twitter/luna_chart_1d_20250109_143022.png",
  "chart_data": {
    "current_price": 0.0134,
    "price_change": 0.0001,
    "price_change_percent": 0.75,
    "data_points": 48,
    "time_range": "2025-01-09 00:00 to 2025-01-09 23:59"
  },
  "technical_analysis": {
    "rsi": {
      "current": 45.2,
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
        "type": "Ascending Triangle",
        "description": "Horizontal resistance with rising support - bullish pattern",
        "confidence": "Medium"
      }
    ],
    "support_levels": [0.0130],
    "resistance_levels": [0.0138]
  }
}
```

### `POST /generate`
Same as GET but accepts JSON payload:
```json
{
  "days": 7
}
```

## Environment Variables

Set these in your Railway deployment:

- `SUPABASE_URL`: Your Supabase project URL
- `SUPABASE_SERVICE_ROLE_KEY`: Your Supabase service role key
- `SUPABASE_BUCKET_NAME`: Your Supabase storage bucket name (default: "Luna-Twitter")

## Deployment to Railway

1. Push this folder to GitHub
2. Connect your GitHub repo to Railway
3. Set the environment variables in Railway dashboard
4. Deploy!

## Usage Examples

```bash
# Generate 1-day chart
curl https://your-railway-app.railway.app/generate

# Generate 7-day chart
curl https://your-railway-app.railway.app/generate?days=7

# Health check
curl https://your-railway-app.railway.app/health
```

## Local Development

```bash
# Install dependencies
pip install -r requirements.txt

# Set environment variables
cp env.example .env
# Edit .env with your Supabase credentials

# Run locally
python app.py
```

The service will be available at `http://localhost:5000`
