"""Select and initialize one provider; other layers never branch on providers."""
import pytz
from app.core.exceptions import ConfigurationError
from app.providers.http import ProviderHTTPClient
from app.providers.fitbit.auth import FitbitTokenManager
from app.providers.fitbit.client import FitbitClient
from app.providers.fitbit.provider import FitbitProvider
from app.providers.google_health.auth import GoogleTokenManager
from app.providers.google_health.client import GoogleHealthClient
from app.providers.google_health.provider import GoogleHealthProvider


def create_provider(settings):
    implementations = {"fitbit": (FitbitTokenManager, FitbitClient, FitbitProvider), "google": (GoogleTokenManager, GoogleHealthClient, GoogleHealthProvider)}
    if settings.health_api_provider not in implementations:
        raise ConfigurationError("Unsupported health provider")
    auth_type, client_type, provider_type = implementations[settings.health_api_provider]
    token = auth_type(settings)
    transport = ProviderHTTPClient(settings, token)
    try:
        token.refresh()
        client = client_type(settings, transport)
        zone = client.get_timezone_name() if settings.local_timezone == "Automatic" else settings.local_timezone
        provider = provider_type(settings, client, pytz.timezone(zone))
        if isinstance(provider, GoogleHealthProvider):
            metadata = client.discover_google_device_metadata()
            provider._metadata = metadata
            if settings.devicename == "Your_Device_Name" and metadata.get("deviceName"):
                provider.device_name = metadata["deviceName"]
        return provider
    except Exception:
        transport.close()
        token.close()
        raise
