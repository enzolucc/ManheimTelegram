# Vehicle Auction Data Telegram Bot

A Telegram bot that provides comprehensive vehicle auction data from Manheim using the python-telegram-bot library. Analyze historical prices, generate trend charts, filter transactions, and more.

## Features

### Core Capabilities
- Look up vehicle auction data by VIN
- Look up vehicle auction data by Year/Make/Model
- Interactive refinement of valuations with color, grade, mileage, and region
- View recent transactions, estimated values, and market trends
- Search history management to track previous lookups

### Data Visualization
- **📈 Price Trend Charts**: Generate visual charts showing historical price trends, with:
  - Historical average prices
  - Individual transaction data points
  - Mileage trend correlation
  - Price forecasts for future values
  - Professional visualization with clear labels

### Advanced Data Management
- **🔍 Transaction Filtering**: Filter auction transaction data by:
  - Condition grade (e.g., show only 4.0+ condition vehicles)
  - Mileage (e.g., under 50,000 miles)
  - Date range (e.g., last 6 months only)
  - Geographic region

- **📄 Pagination for Large Datasets**: Navigate through:
  - Large vehicle data responses
  - Transaction lists with many entries
  - Multi-page results with prev/next controls

### Historical Data
- View valuations from specific dates in the past
- Track how vehicle values have changed over time
- Compare historical averages against recent transactions

## Setup

1. Clone this repository
2. Install dependencies:
   ```
   pip install -r requirements.txt
   ```
3. Set up your Telegram bot:
   - Chat with [@BotFather](https://t.me/botfather) on Telegram
   - Create a new bot with `/newbot` command
   - Copy the API token provided by BotFather

4. Get a Manheim API key:
   - Sign up for Manheim API access at their developer portal
   - Generate an API key

5. Create a `.env` file with your tokens:
   ```
   TELEGRAM_BOT_TOKEN=your_telegram_bot_token_here
   MANHEIM_CLIENT_ID=your_manheim_client_id_here
   MANHEIM_CLIENT_SECRET=your_manheim_client_secret_here
   USE_MANHEIM_UAT=True  # Use 'True' for UAT/test environment, 'False' for production
   ```

6. Start the bot:
   ```
   python bot.py
   ```

## Usage

Once the bot is running, users can interact with it using these commands:

### Basic Commands
- `/start` - Introduction to the bot
- `/help` - List of available commands and features
- `/history` - View your recent lookup history

### Vehicle Lookup
- `/vin [VIN]` - Get auction data for a specific VIN
- `/vin [VIN] color=COLOR grade=GRADE odometer=MILES region=REGION` - Get auction data with specific parameters
- `/vin [VIN] date=YYYY-MM-DD` - Get historical valuation for a specific date
- `/ymm [Year] [Make] [Model]` - Get auction data for a Year/Make/Model
- `/ymm [Year] [Make] [Model] date=YYYY-MM-DD` - Get historical Year/Make/Model data

### Interactive Features
After a search, the bot provides interactive buttons to:
- Refine valuation with specific parameters
- Filter transaction data by various criteria
- Generate price trend charts
- Navigate through paginated results
- View all transactions with filtering options

## Parameter Options

### Common Parameters
- `color` - Vehicle color (e.g., WHITE, BLACK, SILVER)
- `grade` - Vehicle condition grade (e.g., 1.0, 3.5, 4.5) on a 0-5 scale
- `odometer` - Vehicle mileage in miles
- `region` - Geographic region (NE, SE, MW, SW, W)
- `date` - Historical valuation date in YYYY-MM-DD format (must be after 2018-10-08)

### VIN-Specific Options
- Subseries - Specific trim level/subseries (e.g., SE, LX)
- Transmission - Transmission type (e.g., AUTO, MANUAL)

## Transaction Filtering

The bot allows filtering transaction data by:
1. **Grade**: Show only vehicles with grades above a threshold (e.g., 3.0, 4.0)
2. **Mileage**: Show only vehicles with mileage below a threshold (e.g., 50k, 100k)
3. **Date**: Show only transactions within time periods (e.g., last 6 months, last year)
4. **Region**: Show only transactions from specific geographic regions

## Manheim API Integration

This bot uses the official Manheim Valuations API to retrieve auction data. You'll need to register for API access at [Manheim's Developer Portal](https://developer.manheim.com) and obtain client credentials (client ID and client secret) to use this bot.

### API Environments

Manheim provides two environments:
- **UAT (Test)**: Used for development and testing (`https://uat.api.manheim.com`)
- **Production**: Used for live applications (`https://api.manheim.com`)

You can switch between environments by setting the `USE_MANHEIM_UAT` variable in your `.env` file.

### API Endpoints

The bot uses the following Manheim API endpoints:
- `/oauth2/token` - For authentication
- `/valuations/vin/{vin}` - For VIN-based valuations
- `/valuations/vin/{vin}/{subseries}` - For VIN with subseries
- `/valuations/vin/{vin}/{subseries}/{transmission}` - For VIN with subseries and transmission
- `/valuations/years/{year}/makes/{make}/models/{model}` - For Year/Make/Model-based valuations

### Example VIN

For testing in the UAT environment, you can use this example VIN:
- WBA3C1C5XFP853102

Example queries:
```
/vin WBA3C1C5XFP853102
/vin WBA3C1C5XFP853102 color=WHITE grade=3.5 odometer=20000 region=NE
/vin WBA3C1C5XFP853102 date=2023-05-15
/ymm 2020 Honda Accord
```

For more information on the API responses and available fields, refer to the [official API documentation](https://developer.manheim.com/#/apis/marketplace/valuations).