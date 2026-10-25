using System.Text.RegularExpressions;
using LlmStyle.Application;
using LlmStyle.Application.Contracts;
namespace LlmStyle.Infrastructure.Photos;

public sealed partial class LocalPhotoStorage : IPhotoStorage
{
    public const int MaxBytes=10*1024*1024;
    private readonly string directory;
    public LocalPhotoStorage(string directory)
    {
        this.directory=directory; Directory.CreateDirectory(directory);
        foreach(var path in Directory.EnumerateFiles(directory,"draft-*"))
            if(File.GetLastWriteTimeUtc(path)<DateTime.UtcNow.AddDays(-1)) Delete(Path.GetFileName(path));
    }
    [GeneratedRegex(@"^(?:draft-[0-9a-f]{12}|\d+(?:-[0-9a-f]{12})?)\.(jpg|jpeg|png|webp)$")]
    private static partial Regex NamePattern();
    public static void Validate(PhotoUpload upload)
    {
        var ext=Path.GetExtension(upload.Filename).ToLowerInvariant();
        if(ext is not (".jpg" or ".jpeg" or ".png" or ".webp")) throw new ArgumentException("Photo must be .jpg, .jpeg, .png or .webp.");
        if(upload.Bytes.Length==0) throw new ArgumentException("Empty upload.");
        if(upload.Bytes.Length>MaxBytes) throw new StyleException(413,"Photo must be under 10 MB.");
    }
    private string PathFor(string name)
    {
        if(!NamePattern().IsMatch(name)) throw new StyleException(404,"No such photo.");
        return Path.Combine(directory,name);
    }
    public string SaveDraft(PhotoUpload upload)
    {
        Validate(upload); var token=$"draft-{Guid.NewGuid():N}"[..18]+Path.GetExtension(upload.Filename).ToLowerInvariant();
        File.WriteAllBytes(PathFor(token),upload.Bytes); return token;
    }
    public string Claim(string token,int id)
    {
        if(id<1 || !token.StartsWith("draft-",StringComparison.Ordinal)) throw new ArgumentException("A live draft token is required.");
        var source=PathFor(token); if(!File.Exists(source)) throw new StyleException(404,"Draft photo is missing or already saved.");
        // A new owned filename keeps the previous photo intact until its DB reference is committed.
        var name=$"{id}-{token[6..]}"; File.Move(source,PathFor(name)); return name;
    }
    public PhotoFile Read(string name)
    {
        var path=PathFor(name); if(!File.Exists(path)) throw new StyleException(404,"Photo not found.");
        var mime=Path.GetExtension(name) switch { ".png"=>"image/png",".webp"=>"image/webp",_=>"image/jpeg" };
        return new(File.ReadAllBytes(path),mime);
    }
    public void Delete(string? name)
    {
        if(name is null) return;
        try { File.Delete(PathFor(name)); } catch(IOException) { } catch(StyleException) { }
    }
}
