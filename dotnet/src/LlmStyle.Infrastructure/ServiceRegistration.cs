using LlmStyle.Application;
using LlmStyle.Application.Contracts;
using LlmStyle.Infrastructure.Storage;
using LlmStyle.Infrastructure.Photos;
using LlmStyle.Infrastructure.Integrations;
using LlmStyle.Infrastructure.Jobs;
using Microsoft.Extensions.DependencyInjection;
namespace LlmStyle.Infrastructure;

public static class ServiceRegistration
{
    public static IServiceCollection AddStyleApplication(this IServiceCollection services,Func<IServiceProvider,string> dataDirectory,StyleSettings? defaults=null)
    {
        defaults ??= new(Environment.GetEnvironmentVariable("LLM_STYLE_CITY") ?? "Paris",Environment.GetEnvironmentVariable("LLM_STYLE_MODEL") ?? "dolphin-mistral:7b",
            Environment.GetEnvironmentVariable("LLM_STYLE_OLLAMA_URL") ?? "http://localhost:11434",Environment.GetEnvironmentVariable("LLM_STYLE_VISION_MODEL") ?? "gemma3:4b");
        services.AddSingleton<IStyleStore>(sp=>new SqliteStyleStore(Path.Combine(dataDirectory(sp),"llm_style.db"),defaults));
        services.AddSingleton<IPhotoStorage>(sp=>new LocalPhotoStorage(Path.Combine(dataDirectory(sp),"images")));
        services.AddSingleton<ILlmClient>(_=>new OllamaClient()); services.AddSingleton<IWeatherClient>(_=>new WeatherClient());
        services.AddSingleton<IJobQueue,JobQueue>(); services.AddSingleton<IStyleApp,StyleApp>(); return services;
    }
}
