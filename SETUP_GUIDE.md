# Setup Guide - LLM Configuration

## Quick Setup

### 1. Install Dependencies
```bash
pip install -r requirements.txt
playwright install chromium
```

### 2. Configure LLM API

Copy the example environment file:
```bash
cp .env.example .env
```

Then edit `.env` with your LLM provider details.

## Supported Providers

### Option A: Azure OpenAI (Primary)
```env
LLM_API_BASE_URL=https://YOUR-RESOURCE.openai.azure.com/
LLM_API_KEY=your-azure-api-key
LLM_API_VERSION=2024-12-01-preview
LLM_MODEL_NAME=your-deployment-name
EMBEDDING_MODEL_NAME=text-embedding-3-large
```

### Option B: OpenRouter (Multi-Model)
```env
LLM_API_BASE_URL=https://openrouter.ai/api/v1
LLM_API_KEY=your-openrouter-key
LLM_API_VERSION=2024-01-01
LLM_MODEL_NAME=openai/gpt-4
# Or: anthropic/claude-3-opus, google/gemini-pro, etc.
EMBEDDING_MODEL_NAME=text-embedding-3-large
```

### Option C: OpenAI API (Direct)
```env
LLM_API_BASE_URL=https://api.openai.com/v1
LLM_API_KEY=sk-your-openai-key
LLM_API_VERSION=2024-01-01
LLM_MODEL_NAME=gpt-4
EMBEDDING_MODEL_NAME=text-embedding-3-large
```

### Option D: Claude (Anthropic)
```env
LLM_API_BASE_URL=https://api.anthropic.com/v1
LLM_API_KEY=your-anthropic-key
LLM_API_VERSION=2023-06-01
LLM_MODEL_NAME=claude-3-opus-20240229
EMBEDDING_MODEL_NAME=text-embedding-3-large
```

## Testing Your Configuration

After setting up `.env`, test your configuration:

```bash
# Test LLM client
python test_pipeline.py

# Test full pipeline
pytest test_enhanced_pipeline.py -v
```

## Multi-Provider Setup (Advanced)

You can configure a fallback provider for specific tasks:

```env
# Primary provider
LLM_API_BASE_URL=https://YOUR-RESOURCE.openai.azure.com/
LLM_API_KEY=your-azure-key
LLM_MODEL_NAME=gpt-4

# Fallback provider (optional)
FALLBACK_LLM_API_BASE_URL=https://openrouter.ai/api/v1
FALLBACK_LLM_API_KEY=your-openrouter-key
FALLBACK_LLM_MODEL_NAME=anthropic/claude-3-sonnet
```

## Security Best Practices

1. **Never commit `.env` file** - It contains your API keys
2. **Use `.env.example` for templates** - This is safe to commit
3. **Rotate keys regularly** - Change API keys periodically
4. **Use environment-specific files** - `.env.production`, `.env.development`

## Troubleshooting

### "Field required" errors
Make sure you have these required variables in `.env`:
- `LLM_API_BASE_URL`
- `LLM_API_KEY`
- `LLM_MODEL_NAME`

### Provider not detected correctly
Check your `LLM_API_BASE_URL`:
- Azure: Must contain "azure" or "openai.azure.com"
- OpenRouter: Must contain "openrouter"
- OpenAI: Should be "api.openai.com/v1"

### Rate limit errors
- **Azure**: Check your deployment quotas in Azure Portal
- **OpenRouter**: Check your rate limits at openrouter.ai/account
- **OpenAI**: Upgrade your plan or reduce request frequency

## Migration from Old Config

If you have an old `.env` with `AZURE_*` variables:

```bash
# Backup old config
cp .env .env.backup

# Run migration
python migrate_env.py

# Test new config
python test_pipeline.py
```

## Getting API Keys

### Azure OpenAI
1. Go to [Azure Portal](https://portal.azure.com)
2. Create an Azure OpenAI resource
3. Deploy a model (e.g., gpt-4)
4. Get your endpoint and key from "Keys and Endpoint"

### OpenRouter
1. Go to [OpenRouter](https://openrouter.ai)
2. Sign up and verify email
3. Go to "Keys" section
4. Create a new API key
5. Add credits to your account

### OpenAI API
1. Go to [OpenAI Platform](https://platform.openai.com)
2. Sign up and add payment method
3. Go to "API Keys"
4. Create a new secret key

### Anthropic Claude
1. Go to [Anthropic Console](https://console.anthropic.com)
2. Sign up (may require waitlist)
3. Go to "API Keys"
4. Create a new key

## Next Steps

After configuration:
1. Run tests: `python test_pipeline.py`
2. Upload your CV: `python main.py upload-cv cv.pdf`
3. Start job search: `python main.py scrape -p "Your Job Title"`

For full documentation, see [README.md](README.md)
