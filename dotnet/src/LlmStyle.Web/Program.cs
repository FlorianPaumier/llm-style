using System.Text.Json;
using LlmStyle.Application;
using LlmStyle.Application.Contracts;
using LlmStyle.Infrastructure;
using LlmStyle.Web.Endpoints;
using LlmStyle.Infrastructure.Storage;
using Microsoft.AspNetCore.Http.Features;
using LlmStyle.Web.Components;

var builder = WebApplication.CreateBuilder(args);

// Add services to the container.
builder.Services.AddRazorComponents()
    .AddInteractiveServerComponents();

builder.Services.AddCors(options=>options.AddDefaultPolicy(policy=>
{
    var origins=(builder.Configuration["LLM_STYLE_CORS_ORIGINS"] ?? "*").Split(',',StringSplitOptions.RemoveEmptyEntries|StringSplitOptions.TrimEntries);
    if(origins.Contains("*")) policy.AllowAnyOrigin(); else policy.WithOrigins(origins);
    policy.AllowAnyHeader().AllowAnyMethod();
}));
builder.Services.ConfigureHttpJsonOptions(o => o.SerializerOptions.PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower);
builder.Services.Configure<FormOptions>(o => o.MultipartBodyLengthLimit = 210L * 1024 * 1024);
builder.WebHost.ConfigureKestrel(o => o.Limits.MaxRequestBodySize = 210L * 1024 * 1024);
var defaultDataDirectory = Path.GetFullPath(Path.Combine(builder.Environment.ContentRootPath,"../../data"));
var requestedDataDirectory = builder.Configuration["data-dir"];
if (builder.Configuration["import-from"] is {} sourceDirectory)
{
    if (string.IsNullOrWhiteSpace(requestedDataDirectory)) throw new ArgumentException("Import requires --data-dir pointing to a new destination directory.");
    WardrobeImport.Import(sourceDirectory, requestedDataDirectory);
}
builder.Services.AddStyleApplication(sp => sp.GetRequiredService<IConfiguration>()["data-dir"] ?? sp.GetRequiredService<IConfiguration>()["LLM_STYLE_DATA_DIR"] ?? defaultDataDirectory);
builder.Services.AddSingleton<IInstallationInfo,WebInstallationInfo>();
var app = builder.Build();


// Configure the HTTP request pipeline.
if (!app.Environment.IsDevelopment())
{
    app.UseExceptionHandler("/Error", createScopeForErrors: true);
    // The default HSTS value is 30 days. You may want to change this for production scenarios, see https://aka.ms/aspnetcore-hsts.
    app.UseHsts();
}
app.Use(async (context,next) =>
{
    try { await next(); }
    catch (Exception e) when(e is StyleException or ArgumentException or JsonException or BadHttpRequestException)
    {
        if(context.Response.HasStarted) throw;
        context.Response.Clear();
        context.Response.StatusCode = e is StyleException failure ? failure.StatusCode : 422;
        await context.Response.WriteAsJsonAsync(new { detail = e.Message });
    }
});
app.UseStatusCodePagesWithReExecute("/not-found", createScopeForStatusCodePages: true);
if (!app.Environment.IsDevelopment()) app.UseHttpsRedirection();

app.UseCors();
app.UseAntiforgery();

app.MapStaticAssets();

app.MapStyleApi();
WebInstallationInfo.MapInstallation(app);

app.MapRazorComponents<App>()
    .AddInteractiveServerRenderMode()
    .AddAdditionalAssemblies(
        typeof(LlmStyle.UI._Imports).Assembly);

app.Run();

public partial class Program { }
