using System.Net;
using System.Net.NetworkInformation;
using System.Net.Sockets;
using LlmStyle.Application;
using QRCoder;
namespace LlmStyle.Web.Endpoints;

public sealed class WebInstallationInfo : IInstallationInfo
{
    public InstallationInfo Get(string baseUri)
    {
        var uri=new Uri(baseUri);
        var urls=NetworkInterface.GetAllNetworkInterfaces().Where(n=>n.OperationalStatus==OperationalStatus.Up && n.NetworkInterfaceType!=NetworkInterfaceType.Loopback)
            .SelectMany(n=>n.GetIPProperties().UnicastAddresses).Select(a=>a.Address)
            .Where(a=>a.AddressFamily==AddressFamily.InterNetwork && !IPAddress.IsLoopback(a) && !a.ToString().StartsWith("169.254.",StringComparison.Ordinal))
            .Select(a=>$"{uri.Scheme}://{a}:{uri.Port}").Distinct().ToArray();
        return new(false,urls.FirstOrDefault() ?? uri.GetLeftPart(UriPartial.Authority),urls,"/api/app/qr.svg");
    }
    public static void MapInstallation(WebApplication app)
    {
        InstallationInfo Info(HttpRequest request,IInstallationInfo installation)=>installation.Get($"{request.Scheme}://{request.Host}/");
        app.MapGet("/api/app/download",(HttpRequest request,IInstallationInfo installation)=>
        {
            var info=Info(request,installation);
            return new {info.PrimaryUrl,info.LanUrls,info.QrSvgUrl,manifest_url="/manifest.webmanifest",install_hint="Open this address on your phone, then use Add to Home Screen or Install app. Secure hosting is required for full PWA installation."};
        });
        app.MapGet("/api/app/qr.svg",(HttpRequest request,IInstallationInfo installation)=>
        {
            using var generator=new QRCodeGenerator(); using var data=generator.CreateQrCode(Info(request,installation).PrimaryUrl,QRCodeGenerator.ECCLevel.Q);
            using var qr=new SvgQRCode(data); return Results.Text(qr.GetGraphic(5),"image/svg+xml");
        });
    }
}
