using System.Globalization;
using Microsoft.Data.Sqlite;
using LlmStyle.Application;
using LlmStyle.Application.Contracts;
using LlmStyle.Domain.Personas;
using LlmStyle.Domain.Wardrobes;
namespace LlmStyle.Infrastructure.Storage;

public sealed partial class SqliteStyleStore : IStyleStore
{
    private readonly string connectionString;
    private readonly StyleSettings defaults;
    public SqliteStyleStore(string path, StyleSettings defaults)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(path))!);
        connectionString = new SqliteConnectionStringBuilder { DataSource = path, ForeignKeys = true, DefaultTimeout = 5 }.ToString();
        this.defaults = defaults;
        using var c = Open();
        Execute(c, """

CREATE TABLE IF NOT EXISTS personas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    type TEXT NOT NULL CHECK (type IN ('top', 'bottom', 'shoes', 'outerwear', 'accessory')),
    color TEXT,
    warmth INTEGER NOT NULL CHECK (warmth BETWEEN 1 AND 5),
    formality INTEGER NOT NULL CHECK (formality BETWEEN 1 AND 5),
    style_tags TEXT,
    notes TEXT,
    times_worn INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS settings (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    city TEXT,
    model TEXT,
    ollama_url TEXT
);

CREATE TABLE IF NOT EXISTS outfit_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    mood TEXT NOT NULL,
    occasion TEXT NOT NULL,
    weather_json TEXT,
    item_ids_json TEXT NOT NULL,
    rationale TEXT,
    source TEXT
);

""");
        foreach (var (table, name, declaration) in Migrations)
            if (!Rows(c, $"PRAGMA table_info({table})").Any(r => Text(r, "name") == name))
                Execute(c, $"ALTER TABLE {table} ADD COLUMN {name} {declaration}");
        Execute(c, "INSERT OR IGNORE INTO personas (id,name) VALUES (1,'Me'); INSERT OR IGNORE INTO settings(id) VALUES(1)");
        Execute(c, "UPDATE items SET category = 'other_' || type WHERE category IS NULL OR category = ''");
        foreach (var row in Rows(c, "SELECT id,image_path FROM items WHERE image_path IS NOT NULL"))
        {
            var name = Path.GetFileName(Text(row, "image_path")!.Replace('\\', '/'));
            Execute(c, "UPDATE items SET image_path=$0 WHERE id=$1", name, Number(row, "id"));
        }
    }
    private static readonly (string Table, string Name, string Declaration)[] Migrations =
    [
        ("items", "image_path", "TEXT"),
        ("settings", "vision_model", "TEXT"),
        ("outfit_history", "worn_at", "TEXT"),
        ("items", "persona_id", "INTEGER NOT NULL DEFAULT 1"),
        ("outfit_history", "persona_id", "INTEGER NOT NULL DEFAULT 1"),
        ("personas", "description", "TEXT"),
        ("items", "category", "TEXT"),
        ("personas", "gender", "TEXT"),
    ];
    private SqliteConnection Open()
    {
        var c = new SqliteConnection(connectionString); c.Open();
        Execute(c, "PRAGMA journal_mode=WAL; PRAGMA busy_timeout=5000"); return c;
    }
    private static SqliteCommand Command(SqliteConnection c, string sql, params object?[] values)
    {
        var cmd = c.CreateCommand(); cmd.CommandText = sql;
        for (var i=0; i<values.Length; i++) cmd.Parameters.AddWithValue($"${i}", values[i] ?? DBNull.Value);
        return cmd;
    }
    private static int Execute(SqliteConnection c, string sql, params object?[] values)
    { using var cmd = Command(c, sql, values); return cmd.ExecuteNonQuery(); }
    private static List<Dictionary<string, object?>> Rows(SqliteConnection c, string sql, params object?[] values)
    {
        using var cmd = Command(c, sql, values); using var reader = cmd.ExecuteReader();
        var rows = new List<Dictionary<string, object?>>();
        while (reader.Read())
        {
            var row = new Dictionary<string, object?>();
            for (var i=0; i<reader.FieldCount; i++) row[reader.GetName(i)] = reader.IsDBNull(i) ? null : reader.GetValue(i);
            rows.Add(row);
        }
        return rows;
    }
    private static string? Text(Dictionary<string, object?> r, string key) => r.GetValueOrDefault(key)?.ToString();
    private static int Number(Dictionary<string, object?> r, string key) => Convert.ToInt32(r.GetValueOrDefault(key), CultureInfo.InvariantCulture);
    private static int LastId(SqliteConnection c) => Number(Rows(c, "SELECT last_insert_rowid() AS id")[0], "id");
    private static Persona Person(Dictionary<string, object?> r) => new(Number(r,"id"), Text(r,"name")!, Text(r,"description"), Text(r,"gender") ?? "unspecified");
    private static Persona RequirePerson(SqliteConnection c, int id) => Rows(c,"SELECT * FROM personas WHERE id=$0",id).Select(Person).FirstOrDefault() ?? throw new StyleException(404,"Persona not found.");
    public IReadOnlyList<Persona> ListPersonas() { using var c=Open(); return Rows(c,"SELECT * FROM personas ORDER BY id").Select(Person).ToArray(); }
    public Persona SavePersona(PersonaInput input, int? id = null, IReadOnlySet<string>? fields = null)
    {
        using var c=Open(); using var transaction=c.BeginTransaction(deferred:false); var current=id is null ? null : RequirePerson(c,id.Value);
        var name=input.Name ?? current?.Name ?? "";
        _ = new PersonaName(name.Trim());
        Garment.CheckText(input.Description,500,"description");
        var gender=(fields is null || fields.Contains("gender")) ? input.Gender ?? "unspecified" : current!.Gender;
        if (gender is not ("male" or "female" or "unspecified")) throw new ArgumentException("Invalid gender.");
        var description=(fields is null || fields.Contains("description")) ? input.Description : current?.Description;
        if (id is null) { Execute(c,"INSERT INTO personas(name,description,gender) VALUES($0,$1,$2)",name.Trim(),string.IsNullOrEmpty(description)?null:description,gender); id=LastId(c); }
        else Execute(c,"UPDATE personas SET name=$0,description=$1,gender=$2 WHERE id=$3",name.Trim(),string.IsNullOrEmpty(description)?null:description,gender,id);
        transaction.Commit(); return RequirePerson(c,id.Value);
    }
    public void DeletePersona(int id)
    {
        using var c=Open(); using var transaction=c.BeginTransaction(deferred:false);
        _=RequirePerson(c,id);
        if (Rows(c,"SELECT id FROM personas").Count<=1) throw new StyleException(400,"Can't delete the last persona.");
        if (Rows(c,"SELECT id FROM items WHERE persona_id=$0 LIMIT 1",id).Count>0) throw new StyleException(409,"Move or delete this person's items first.");
        Execute(c,"DELETE FROM personas WHERE id=$0",id); transaction.Commit();
    }
}
