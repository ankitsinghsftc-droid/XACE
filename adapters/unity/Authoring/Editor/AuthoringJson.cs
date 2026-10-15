using System;
using System.Collections;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Security.Cryptography;
using System.Text;

namespace Xace.Authoring.Editor
{
    // NEC wire JSON: strings/bools/null/arrays/objects only, canonical ASCII encoding.
    public static class AuthoringJson
    {
        public const int MaxBytes = 16 * 1024 * 1024;
        public static void Need(bool condition, string message)
        { if (!condition) throw new InvalidDataException(message); }
        public static Dictionary<string, object> Obj(object value)
        { return value as Dictionary<string, object> ?? throw new InvalidDataException("Expected object"); }
        public static string Text(Dictionary<string,object> value, string key)
        { return value[key] as string ?? throw new InvalidDataException("Expected text: " + key); }
        public static string Hash(byte[] bytes)
        { using (var sha=SHA256.Create()) return BitConverter.ToString(sha.ComputeHash(bytes)).Replace("-","").ToLowerInvariant(); }
        public static string Hash(string text) { return Hash(Encoding.UTF8.GetBytes(text)); }
        public static string Encode(object value)
        {
            var result=new StringBuilder(); Write(result,value,0);
            Need(Encoding.UTF8.GetByteCount(result.ToString())<=MaxBytes,"JSON byte limit"); return result.ToString();
        }
        static void Write(StringBuilder b, object value, int depth)
        {
            Need(depth<=24,"JSON depth limit");
            if(value==null) {b.Append("null");return;}
            if(value is bool flag) {b.Append(flag?"true":"false");return;}
            if(value is string text)
            {
                b.Append('"');
                foreach(char c in text)
                    switch(c) {
                    case '"':b.Append("\\\"");break; case '\\':b.Append("\\\\");break;
                    case '\b':b.Append("\\b");break; case '\f':b.Append("\\f");break;
                    case '\n':b.Append("\\n");break; case '\r':b.Append("\\r");break; case '\t':b.Append("\\t");break;
                    default:if(c<32 || c>=127)b.Append("\\u"+((int)c).ToString("x4"));else b.Append(c);break;
                    }
                b.Append('"');return;
            }
            if(value is IDictionary<string,object> map)
            {
                b.Append('{');bool first=true;
                var keys=new List<string>(map.Keys);keys.Sort(StringComparer.Ordinal);
                foreach(var k in keys){if(!first)b.Append(',');first=false;Write(b,k,depth+1);b.Append(':');Write(b,map[k],depth+1);}
                b.Append('}');return;
            }
            if(value is IEnumerable sequence)
            {
                b.Append('[');bool first=true;
                foreach(var item in sequence){if(!first)b.Append(',');first=false;Write(b,item,depth+1);}b.Append(']');return;
            }
            throw new InvalidDataException("Wire numbers must be strings");
        }
        public static object Parse(string text)
        {
            Need(Encoding.UTF8.GetByteCount(text)<=MaxBytes,"JSON byte limit");
            var parser=new Parser(text);var value=parser.Read(0);parser.Space();Need(parser.Index==text.Length,"Trailing JSON");return value;
        }
        sealed class Parser
        {
            readonly string source;public int Index;int count;
            public Parser(string source){this.source=source;}
            public void Space(){while(Index<source.Length && char.IsWhiteSpace(source[Index]))Index++;}
            char Take(){Need(Index<source.Length,"Truncated JSON");return source[Index++];}
            string String()
            {
                Need(Take()=='"',"Expected string");var b=new StringBuilder();
                while(true){char c=Take();if(c=='"')break;Need(c>=32,"Control character");
                    if(c=='\\'){c=Take();switch(c){case '"':case '\\':case '/':break;case 'b':c='\b';break;case 'f':c='\f';break;case 'n':c='\n';break;case 'r':c='\r';break;case 't':c='\t';break;case 'u':Need(Index+4<=source.Length,"Short unicode");c=(char)int.Parse(source.Substring(Index,4),NumberStyles.HexNumber,CultureInfo.InvariantCulture);Index+=4;break;default:throw new InvalidDataException("Bad escape");}}
                    b.Append(c);Need(b.Length<=4096,"String limit");}
                return b.ToString();
            }
            public object Read(int depth)
            {
                Need(depth<=24 && ++count<=1000000,"JSON structure limit");Space();Need(Index<source.Length,"Missing value");
                char c=source[Index];if(c=='"')return String();
                if(c=='{' || c=='[')
                {
                    Index++;Space();var map=new Dictionary<string,object>(StringComparer.Ordinal);var list=new List<object>();char end=c=='{'?'}':']';
                    if(Index<source.Length && source[Index]==end){Index++;return c=='{'?(object)map:list;}
                    while(true){Space();if(c=='{'){string key=String();Need(key.Length<=256 && !map.ContainsKey(key),"Duplicate/long key");Space();Need(Take()==':',"Missing colon");map.Add(key,Read(depth+1));}else list.Add(Read(depth+1));Space();char sep=Take();if(sep==end)break;Need(sep==',',"Missing comma");}
                    return c=='{'?(object)map:list;
                }
                foreach(string literal in new[]{"true","false","null"})
                    if(source.Substring(Index).StartsWith(literal,StringComparison.Ordinal)){Index+=literal.Length;return literal=="null"?null:(object)(literal=="true");}
                throw new InvalidDataException("Numeric/unknown JSON token");
            }
        }
    }
}
