# Vehicle Auction Data Telegram Bot

A Telegram bot that provides vehicle auction data from Manheim using the python-telegram-bot library.

## Features

- Look up vehicle auction data by VIN
- Look up vehicle auction data by Year/Make/Model
- Interactive refinement of valuations with color, grade, mileage, and region
- View recent transactions, estimated values, and market trends

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

- `/start` - Introduction to the bot
- `/help` - List of available commands
- `/vin [VIN]` - Get auction data for a specific VIN
- `/vin [VIN] color=COLOR grade=GRADE odometer=MILES region=REGION` - Get auction data with specific parameters
- `/ymm [Year] [Make] [Model]` - Get auction data for a Year/Make/Model

## Note on Manheim API

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

Example query with parameters:
```
/vin WBA3C1C5XFP853102 color=WHITE grade=3.5 odometer=20000 region=NE
```

Supported query parameters:
- `color` - Vehicle color (e.g., WHITE, BLACK, SILVER)
- `grade` - Vehicle condition grade (e.g., 1.0, 3.5, 4.5) on a 0-5 scale
- `odometer` - Vehicle mileage in miles
- `region` - Geographic region (NE, SE, MW, SW, W)

The bot also features an interactive refinement process where you can select these parameters using clickable buttons after performing an initial VIN search.

For more information on the API responses and available fields, refer to the [official API documentation](https://developer.manheim.com/#/apis/marketplace/valuations).