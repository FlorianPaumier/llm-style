using LlmStyle.Application.Contracts;
using LlmStyle.Infrastructure.Photos;
namespace LlmStyle.Infrastructure.Tests;
public sealed class PhotoTests : IDisposable
{
    private readonly string directory=Path.Combine(Path.GetTempPath(),"llm-style-tests",Guid.NewGuid().ToString("N"));
    [Fact]
    public void PhotosHaveOpaqueSingleUseTokensAndIndependentOwnership()
    {
        var photos=new LocalPhotoStorage(directory);
        var a=photos.SaveDraft(new("shirt.jpg",[1,2,3])); var b=photos.SaveDraft(new("shirt.jpg",[1,2,3]));
        Assert.NotEqual(a,b); var first=photos.Claim(a,1); var second=photos.Claim(b,2);
        Assert.Throws<StyleException>(()=>photos.Claim(a,3));
        photos.Delete(first); Assert.Equal(new byte[] {1,2,3},photos.Read(second).Bytes);
        Assert.Throws<StyleException>(()=>photos.Read("../secret.jpg"));
    }
    [Fact]
    public void RejectsUnsupportedEmptyOrOversizedPhotos()
    {
        var photos=new LocalPhotoStorage(directory);
        Assert.Throws<ArgumentException>(()=>photos.SaveDraft(new("x.svg",[1])));
        Assert.Throws<ArgumentException>(()=>photos.SaveDraft(new("x.jpg",[])));
        Assert.Throws<StyleException>(()=>photos.SaveDraft(new("x.jpg",new byte[10*1024*1024+1])));
    }
    public void Dispose() { if(Directory.Exists(directory)) Directory.Delete(directory,true); }
}
