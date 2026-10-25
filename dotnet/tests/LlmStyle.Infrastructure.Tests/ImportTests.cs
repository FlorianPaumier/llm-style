using System.Security.Cryptography;
using LlmStyle.Application.Contracts;
using LlmStyle.Infrastructure.Storage;
using Microsoft.Data.Sqlite;
namespace LlmStyle.Infrastructure.Tests;
public class ImportTests
{
    [Fact]
    public void ImportCopiesAndMigratesWithoutChangingSourceAndRefusesOverwrite()
    {
        var root=Path.Combine(Path.GetTempPath(),"llm-style-import",Guid.NewGuid().ToString("N"));
        var source=Path.Combine(root,"source"); var destination=Path.Combine(root,"copy"); Directory.CreateDirectory(source);
        try
        {
            var db=Path.Combine(source,"llm_style.db"); var store=new SqliteStyleStore(db,new());
            var item=store.SaveItem(new() {Name="Old shirt",Category="shirt",Warmth=2,Formality=2});
            store.SetPhoto(item.Id,"C:\\old\\1.jpg"); Directory.CreateDirectory(Path.Combine(source,"images")); File.WriteAllBytes(Path.Combine(source,"images","1.jpg"),[1,2,3]);
            SqliteConnection.ClearAllPools(); var checksum=SHA256.HashData(File.ReadAllBytes(db));
            WardrobeImport.Import(source,destination);
            var copied=new SqliteStyleStore(Path.Combine(destination,"llm_style.db"),new());
            Assert.Equal("Old shirt",copied.GetItem(item.Id).Name); Assert.Equal("1.jpg",copied.ImageName(item.Id));
            Assert.Equal(new byte[]{1,2,3},File.ReadAllBytes(Path.Combine(destination,"images","1.jpg")));
            Assert.Equal(checksum,SHA256.HashData(File.ReadAllBytes(db)));
            Assert.Throws<IOException>(()=>WardrobeImport.Import(source,destination));
        }
        finally { SqliteConnection.ClearAllPools(); if(Directory.Exists(root)) Directory.Delete(root,true); }
    }
}
