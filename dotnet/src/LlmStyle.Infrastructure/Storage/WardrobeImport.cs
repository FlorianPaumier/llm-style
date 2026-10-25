using System.Text.RegularExpressions;
using LlmStyle.Application.Contracts;
using Microsoft.Data.Sqlite;
namespace LlmStyle.Infrastructure.Storage;

public static class WardrobeImport
{
    public static void Import(string sourceDirectory,string destinationDirectory)
    {
        sourceDirectory=Path.GetFullPath(sourceDirectory); destinationDirectory=Path.GetFullPath(destinationDirectory);
        if(Directory.Exists(destinationDirectory) || File.Exists(destinationDirectory)) throw new IOException("Import destination already exists. Choose a new data directory.");
        var sourceDb=Path.Combine(sourceDirectory,"llm_style.db"); if(!File.Exists(sourceDb)) throw new FileNotFoundException("No llm_style.db in the source directory.");
        var stage=destinationDirectory+".import-"+Guid.NewGuid().ToString("N"); Directory.CreateDirectory(stage);
        try
        {
            using(var source=new SqliteConnection(new SqliteConnectionStringBuilder {DataSource=sourceDb,Mode=SqliteOpenMode.ReadOnly,Pooling=false}.ToString()))
            using(var destination=new SqliteConnection(new SqliteConnectionStringBuilder {DataSource=Path.Combine(stage,"llm_style.db"),Pooling=false}.ToString()))
            { source.Open(); destination.Open(); source.BackupDatabase(destination); }
            var store=new SqliteStyleStore(Path.Combine(stage,"llm_style.db"),new()); Directory.CreateDirectory(Path.Combine(stage,"images"));
            foreach(var person in store.ListPersonas())
            foreach(var item in store.Wardrobe(person.Id))
            {
                var filename=store.ImageName(item.Id); if(filename is null) continue;
                if(!Regex.IsMatch(filename,@"^\d+(?:-[0-9a-f]{12})?\.(jpg|jpeg|png|webp)$")) throw new IOException("The source contains an unsupported photo filename.");
                File.Copy(Path.Combine(sourceDirectory,"images",filename),Path.Combine(stage,"images",filename),overwrite:true);
            }
            SqliteConnection.ClearAllPools(); Directory.Move(stage,destinationDirectory);
        }
        catch { SqliteConnection.ClearAllPools(); if(Directory.Exists(stage)) Directory.Delete(stage,true); throw; }
    }
}
