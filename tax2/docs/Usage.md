# Tax2 Usage Guide

## Installation

No installation required. Simply run the executable:

```bash
./tax2
```

## Basic Usage

### Launch the Application
```bash
./tax2
```

This will:
1. Start the web server on port 8000
2. Automatically open your browser
3. Display the tax calculator interface

### Command-Line Options

**Custom Port**:
```bash
./tax2 --port 9000
```

**Disable Auto-Browser**:
```bash
./tax2 --no-browser
```

**Custom Rules Directory**:
```bash
./tax2 /path/to/custom/rules
```

## Features

### Tax Calculation Modes

1. **Rules Engine** (default)
   - Computes taxes directly from YAML rule files
   - Always uses the latest logic
   - Ideal for testing rule changes

2. **Lookup Table**
   - Fast pre-computed results
   - Requires table generation first
   - Good for production use

### Generating Tables

Use the built-in table generation endpoint:
1. Open the app
2. Go to "Generate Tables" (if UI supports it)
3. Or use API directly:

```bash
curl -X POST http://127.0.0.1:8000/api/generate-tables 
  -H "Content-Type: application/json" 
  -d '{"year": 2025, "state": "GA", "filing_status": "single"}'
```

### QIF Export

1. Enter your income and select filing status
2. Review calculated taxes
3. Configure QIF settings in right panel:
   - Transaction date
   - Payee name
   - Account categories
4. Click "Download QIF"
5. Import into Quicken or Moneydance

## Customization

### Adding New Tax Years

1. Create YAML files:
   - `rules/federal/2026.yaml`
   - `rules/states/GA/2026.yaml`

2. Restart the application

3. New year appears in dropdown

### Adding New States

1. Create directory: `rules/states/TX/`
2. Add YAML file: `rules/states/TX/2025.yaml`
3. Modify API endpoint to support state selection
4. Restart application

## Troubleshooting

**Port already in use**:
```bash
./tax2 --port 9000
```

**Dependencies not installing**:
```bash
rm -rf .tax2_venv
./tax2  # Will recreate and reinstall
```

**Calculation seems wrong**:
- Check YAML rules for typos
- Verify year is correct
- Try switching between rules/table mode
- Compare with previous year's rules
