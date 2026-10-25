using LlmStyle.Application;
using LlmStyle.Domain.Wardrobes;
namespace LlmStyle.Infrastructure.Tests;
public class ArchitectureTests
{
    [Fact]
    public void DomainAndApplicationCannotDependOnOuterLayers()
    {
        Assert.DoesNotContain(typeof(Garment).Assembly.GetReferencedAssemblies(),a=>a.Name!.StartsWith("LlmStyle.") || a.Name!.StartsWith("Microsoft."));
        Assert.DoesNotContain(typeof(StyleApp).Assembly.GetReferencedAssemblies(),a=>a.Name!.StartsWith("LlmStyle.Infrastructure") || a.Name!.StartsWith("LlmStyle.UI") || a.Name!.StartsWith("Microsoft.AspNetCore") || a.Name!.StartsWith("Microsoft.Data"));
    }
}
