using LlmStyle.Application;
namespace LlmStyle.Desktop;
public sealed class DesktopInstallationInfo : IInstallationInfo
{
    public InstallationInfo Get(string baseUri)=>new(true,"",[],null);
}
