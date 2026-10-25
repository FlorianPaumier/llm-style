using System.Collections.Concurrent;
using System.Globalization;
using System.Text.Json;
using LlmStyle.Application;
using LlmStyle.Application.Contracts;
namespace LlmStyle.Infrastructure.Integrations;

public sealed class WeatherClient(HttpClient? http=null) : IWeatherClient, IDisposable
{
    private readonly HttpClient client=http ?? new() {Timeout=TimeSpan.FromSeconds(8)};
    private readonly ConcurrentDictionary<string,(DateTimeOffset At,Weather Value)> cache=new();
    public async Task<Weather> CurrentAsync(string city,CancellationToken cancellationToken=default)
    {
        if(cache.TryGetValue(city,out var old) && old.At>DateTimeOffset.UtcNow.AddMinutes(-30)) return old.Value;
        try
        {
            using var geo=await GetAsync($"https://geocoding-api.open-meteo.com/v1/search?name={Uri.EscapeDataString(city)}&count=1&language=en",cancellationToken);
            if(!geo.RootElement.TryGetProperty("results",out var results) || results.GetArrayLength()==0) throw new JsonException("City not found.");
            var loc=results[0]; string Coordinate(string key)=>loc.GetProperty(key).GetDouble().ToString(CultureInfo.InvariantCulture);
            using var forecast=await GetAsync($"https://api.open-meteo.com/v1/forecast?latitude={Coordinate("latitude")}&longitude={Coordinate("longitude")}&current=temperature_2m,apparent_temperature,precipitation,weather_code,wind_speed_10m",cancellationToken);
            var current=forecast.RootElement.GetProperty("current");
            var result=new Weather(loc.GetProperty("name").GetString()!,current.GetProperty("temperature_2m").GetDouble(),current.GetProperty("apparent_temperature").GetDouble(),
                current.GetProperty("precipitation").GetDouble(),current.GetProperty("wind_speed_10m").GetDouble(),current.GetProperty("weather_code").GetInt32(),DateTimeOffset.UtcNow.ToString("O"));
            cache[city]=(DateTimeOffset.UtcNow,result); return result;
        }
        catch(Exception e) when(e is not OperationCanceledException || !cancellationToken.IsCancellationRequested)
        { if(old.Value is not null) return old.Value; throw new StyleException(503,"Live weather is unavailable. Check your city and internet connection, or set the temperature yourself."); }
    }
    private async Task<JsonDocument> GetAsync(string url,CancellationToken ct)
    { using var response=await client.GetAsync(url,ct); response.EnsureSuccessStatusCode(); return await JsonDocument.ParseAsync(await response.Content.ReadAsStreamAsync(ct),cancellationToken:ct); }
    public void Dispose()=>client.Dispose();
}
