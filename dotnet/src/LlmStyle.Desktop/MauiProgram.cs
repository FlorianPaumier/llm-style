using Microsoft.Extensions.Logging;
using LlmStyle.Infrastructure;
using LlmStyle.Application;

namespace LlmStyle.Desktop;

public static class MauiProgram
{
    public static MauiApp CreateMauiApp()
    {
        var builder = MauiApp.CreateBuilder();
        builder
            .UseMauiApp<App>()
            .ConfigureFonts(fonts =>
            {
                fonts.AddFont("OpenSans-Regular.ttf", "OpenSansRegular");
            });

        builder.Services.AddMauiBlazorWebView();
        builder.Services.AddStyleApplication(_ => FileSystem.AppDataDirectory);
        builder.Services.AddSingleton<IInstallationInfo,DesktopInstallationInfo>();

#if DEBUG
        builder.Services.AddBlazorWebViewDeveloperTools();
        builder.Logging.AddDebug();
#endif

        return builder.Build();
    }
}
