#!/usr/bin/env python
"""Тест конфигурации - проверка что все поля загружаются корректно."""

def test_config():
    """Проверить что конфигурация загружается без ошибок."""
    try:
        from app.config import settings
        print("✅ Config loaded successfully")
        
        # Проверить AI Provider настройки
        print(f"\n📊 AI Provider Configuration:")
        print(f"  AI_PROVIDER: {settings.AI_PROVIDER}")
        print(f"  OPENAI_API_KEY: {'✅ Set' if settings.OPENAI_API_KEY else '❌ Not set'}")
        print(f"  ANTHROPIC_API_KEY: {'✅ Set' if settings.ANTHROPIC_API_KEY else '❌ Not set'}")
        
        # Проверить Claude настройки
        print(f"\n🤖 Claude Configuration:")
        print(f"  CLAUDE_MODEL: {settings.CLAUDE_MODEL}")
        print(f"  CLAUDE_MAX_TOKENS: {settings.CLAUDE_MAX_TOKENS}")
        print(f"  CLAUDE_TIMEOUT: {settings.CLAUDE_TIMEOUT}")
        print(f"  CLAUDE_ENABLE_CACHING: {settings.CLAUDE_ENABLE_CACHING}")
        
        # Проверить Browser диагностику
        print(f"\n🌐 Browser Diagnostics:")
        print(f"  BROWSER_NETWORK_LOG: {settings.BROWSER_NETWORK_LOG}")
        print(f"  BROWSER_CONSOLE_LOG: {settings.BROWSER_CONSOLE_LOG}")
        
        # Проверить Store URLs
        print(f"\n🏪 Store URLs:")
        print(f"  CLASH_ROYALE: {settings.CLASH_ROYALE_STORE_URL}")
        print(f"  BRAWL_STARS: {settings.BRAWL_STARS_STORE_URL}")
        
        return True
        
    except Exception as e:
        print(f"❌ Config error: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_ai_provider():
    """Проверить что AI провайдер инициализируется."""
    try:
        from app.core.ai_product_search import AIProductSearch
        
        ai = AIProductSearch()
        
        if ai.provider:
            print(f"\n✅ AI Provider initialized successfully")
            print(f"  Provider type: {type(ai.provider).__name__}")
            print(f"  Available: {ai.provider.is_available()}")
        else:
            print(f"\n⚠️  AI Provider not initialized (no API keys set)")
            
        return True
        
    except Exception as e:
        print(f"\n❌ AI Provider error: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    print("=" * 60)
    print("🧪 Testing Configuration")
    print("=" * 60)
    
    config_ok = test_config()
    provider_ok = test_ai_provider()
    
    print("\n" + "=" * 60)
    if config_ok and provider_ok:
        print("✅ All tests passed!")
        print("\n📝 Next steps:")
        print("  1. Set API keys in .env")
        print("  2. Install: pip install anthropic>=0.18.0 tenacity>=8.2.0")
        print("  3. Follow: .kiro/specs/ai-vision-claude-migration/tasks.md")
    else:
        print("❌ Some tests failed - check errors above")
    print("=" * 60)
