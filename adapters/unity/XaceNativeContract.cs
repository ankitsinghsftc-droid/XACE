// XP-016: presentation-only readers. No gameplay/noun dispatch or native contacts.
using System;
using System.Collections.Generic;
using System.Globalization;
using System.Security.Cryptography;
using System.Text;
using UnityEngine;

namespace Xace.Adapter.Unity
{
    public sealed class XaceCanonicalObject : MonoBehaviour
    {
        public string ObjectId;
        public Dictionary<string,object> Semantics;
        public SortedDictionary<string,Dictionary<string,object>> WorldObjects = new SortedDictionary<string,Dictionary<string,object>>(StringComparer.Ordinal);
    }
    public static class XaceCanonical
    {
        public const long MaxExact = 9007199254740991;
        public static Dictionary<string, object> Object(object value)
        { return value as Dictionary<string, object> ?? throw new FormatException("Expected object"); }
        public static Dictionary<string, object> Parse(string value)
        { return Object(XaceJson.DeserializeObject(value)); }
        public static object Get(Dictionary<string, object> obj, string key)
        { return obj.TryGetValue(key, out var value) ? value : throw new FormatException("Missing " + key); }
        public static long Integer(object value, long minimum = -MaxExact)
        {
            if (!(value is long) && !(value is int) && !(value is double)) throw new FormatException("Expected integer");
            double number = Convert.ToDouble(value, CultureInfo.InvariantCulture);
            if (double.IsNaN(number) || double.IsInfinity(number) || number < minimum || number > MaxExact || Math.Truncate(number) != number)
                throw new FormatException("Integer outside exact native profile");
            return Convert.ToInt64(value, CultureInfo.InvariantCulture);
        }
        public static string Text(Dictionary<string, object> obj, string key)
        { return Get(obj, key) as string ?? throw new FormatException("Expected string " + key); }
        public static string Hash(string value)
        {
            using (var sha = SHA256.Create())
                return BitConverter.ToString(sha.ComputeHash(Encoding.UTF8.GetBytes(value))).Replace("-", "").ToLowerInvariant();
        }
        // Canonical: right handed, Y up, metres. Unity reflects Z.
        public static Vector3 Vector(Dictionary<string, object> obj, bool scale = false)
        {
            float x = Integer(Get(obj,"x"))/1000000f, y = Integer(Get(obj,"y"))/1000000f, z = Integer(Get(obj,"z"))/1000000f;
            return new Vector3(x, y, scale ? z : -z);
        }
        public static Quaternion Rotation(Dictionary<string, object> obj)
        {
            var q = new Quaternion(-Integer(Get(obj,"x"))/1000000f, -Integer(Get(obj,"y"))/1000000f,
                Integer(Get(obj,"z"))/1000000f, Integer(Get(obj,"w"))/1000000f);
            if (Quaternion.Dot(q,q) < 0.000001f) throw new FormatException("Zero rotation");
            return q.normalized;
        }
        public static void ValidateEntities(List<object> entities)
        {
            var parents = new Dictionary<long,long>(); long last = 0;
            foreach (var value in entities)
            {
                var entity = Object(value); long id = Integer(Get(entity,"id"),1);
                if (id <= last) throw new FormatException("Unsorted/duplicate entity"); last = id;
                var components = Object(Get(entity,"components"));
                foreach (var component in components)
                {
                    if (!uint.TryParse(component.Key, out var type) || type == 0 || !(component.Value is string))
                        throw new FormatException("Invalid component envelope");
                    Parse((string)component.Value);
                }
                if(!components.ContainsKey("1")){parents[id]=0;continue;}
                var transform = Parse(Text(components,"1"));
                Vector(Object(Get(transform,"position"))); var scale = Vector(Object(Get(transform,"scale")),true);
                if (scale.x == 0 || scale.y == 0 || scale.z == 0) throw new FormatException("Invalid scale");
                Rotation(Object(Get(transform,"rotation")));
                parents[id] = Integer(Get(transform,"parent_entity_id"),0);
            }
            foreach (long id in parents.Keys)
            {
                var seen = new HashSet<long>(); long current = id;
                while (current != 0)
                { if (!seen.Add(current) || !parents.ContainsKey(current)) throw new FormatException("Unresolved/cyclic parent"); current = parents[current]; }
            }
        }
    }

    public sealed class XaceNativeWorld
    {
        public Dictionary<string, object> Data { get; private set; }
        public Dictionary<string,long> Bindings { get; private set; } = new Dictionary<string,long>(StringComparer.Ordinal);
        public void Load(string raw, string expectedHash)
        {
            if (XaceCanonical.Hash(raw) != expectedHash) throw new FormatException("World digest mismatch");
            var world = XaceCanonical.Parse(raw);
            if (XaceCanonical.Text(world,"schema") != "xace.world_contract.v3" || XaceCanonical.Integer(XaceCanonical.Get(world,"contract_version")) != 3)
                throw new FormatException("Unsupported world version");
            foreach (object value in (List<object>)XaceCanonical.Get(world,"geometry_profiles"))
            { var profile = XaceCanonical.Object(value); if (XaceCanonical.Text(profile,"id") != "world.aabb.v1" && (bool)XaceCanonical.Get(profile,"required")) throw new FormatException("Unsupported required geometry"); }
            var ids = new HashSet<string>();
            foreach (object value in (List<object>)XaceCanonical.Get(world,"objects"))
            {
                var obj = XaceCanonical.Object(value);
                if (!ids.Add(XaceCanonical.Text(obj,"id"))) throw new FormatException("Duplicate world object");
                if (obj.TryGetValue("geometry",out var geometry) && geometry != null && XaceCanonical.Text(XaceCanonical.Object(geometry),"profile") != "world.aabb.v1")
                    throw new FormatException("Unsupported object geometry");
            }
            Data = world; Bindings.Clear();
        }
        public void Bind(Dictionary<string,object> bindings, List<object> entities)
        {
            var byId = new Dictionary<long,Dictionary<string,object>>();
            foreach (var value in entities) { var e=XaceCanonical.Object(value); byId.Add(XaceCanonical.Integer(XaceCanonical.Get(e,"id"),1),e); }
            var next = new Dictionary<string,long>(StringComparer.Ordinal);
            foreach (var value in (List<object>)XaceCanonical.Get(Data,"objects"))
            {
                var obj=XaceCanonical.Object(value); string key=XaceCanonical.Text(obj,"id");
                if (!bindings.TryGetValue(key,out var raw) || !(raw is string) || !long.TryParse((string)raw,out var id) || id<=0 || id>XaceCanonical.MaxExact || !byId.ContainsKey(id))
                    throw new FormatException("Missing/duplicate canonical object binding");
                var components=XaceCanonical.Object(XaceCanonical.Get(byId[id],"components"));
                if (obj.TryGetValue("geometry",out var g) && g != null)
                {
                    var geometry=XaceCanonical.Object(g); var collider=XaceCanonical.Parse(XaceCanonical.Text(components,"4"));
                    if (XaceCanonical.Text(collider,"shape")!="BOX") throw new FormatException("Canonical geometry mismatch");
                    foreach (string field in new[]{"size","offset","is_trigger","layer_mask"})
                    {
                        object actual = field == "layer_mask" && !collider.ContainsKey(field) ? (object)1L : XaceCanonical.Get(collider,field);
                        if (XaceJson.Serialize(XaceCanonical.Get(geometry,field)) != XaceJson.Serialize(actual)) throw new FormatException("Canonical geometry mismatch");
                    }
                }
                next.Add(key,id);
            }
            Bindings=next;
        }
    }

    public sealed class XaceSessionState
    {
        public static readonly string[] Supported = {"session.projection.v1","input.timed.v1","world.aabb.v1","world.semantic_bindings.v3"};
        public string OfferJson {get;private set;} = "";
        public string Credential {get;private set;} = "";
        public long PeerId {get;private set;}
        public long PlayerId {get;private set;}
        public long ControllerId {get;private set;}
        public long NextTick {get;private set;}
        public long Generation {get;private set;}
        public bool Recovering {get;private set;} = true;
        public bool Enabled => OfferJson.Length != 0;
        public XaceNativeWorld World {get;} = new XaceNativeWorld();
        private Dictionary<string,object> epoch;
        private string cgsHash;
        private long sequence, requestedTick = -1;
        private bool sent;
        public void Configure(string ticketJson, string worldJson)
        {
            var ticket=XaceCanonical.Parse(ticketJson);
            if (XaceCanonical.Text(ticket,"schema")!="xace.session_ticket.v1") throw new FormatException("Unsupported ticket");
            var offer=XaceCanonical.Parse(XaceCanonical.Text(ticket,"offer_json"));
            var contract=XaceCanonical.Object(XaceCanonical.Get(offer,"contract"));
            if (XaceCanonical.Text(contract,"schema")!="xace.session_contract.v1") throw new FormatException("Unsupported session");
            foreach (var cap in (List<object>)XaceCanonical.Get(contract,"required_capabilities"))
                if (!(cap is string) || Array.IndexOf(Supported,(string)cap)<0) throw new FormatException("Unsupported required capability");
            var client=XaceCanonical.Object(XaceCanonical.Get(offer,"client"));
            XaceCanonical.Object(XaceCanonical.Get(client,"adapter"))["engine"]="unity";
            client["capabilities"]=new List<object>(Supported);
            var gameplay=XaceCanonical.Object(XaceCanonical.Get(contract,"gameplay"));
            cgsHash=XaceCanonical.Text(XaceCanonical.Object(XaceCanonical.Get(gameplay,"cgs")),"cgs_hash");
            World.Load(worldJson,XaceCanonical.Text(XaceCanonical.Object(XaceCanonical.Get(XaceCanonical.Object(XaceCanonical.Get(gameplay,"world")),"artifact")),"content_hash"));
            epoch=XaceCanonical.Object(XaceCanonical.Get(contract,"epoch"));
            XaceCanonical.Integer(XaceCanonical.Get(epoch,"ruleset_epoch"),0);
            OfferJson=XaceJson.Serialize(offer); Credential=XaceCanonical.Text(ticket,"credential");
            PeerId=XaceCanonical.Integer(XaceCanonical.Get(ticket,"peer_id"),1); ControllerId=XaceCanonical.Integer(XaceCanonical.Get(ticket,"controller_id"),1);
            PlayerId=0; Generation=0; Recovering=true; requestedTick=-1;
        }
        // Returns accept/drop/recover. Invalid identities/initial projections throw.
        public string Verify(Dictionary<string,object> message)
        {
            string kind=XaceCanonical.Text(message,"msg_type");
            bool initial=kind=="handshake_ack", baseline=kind=="session_baseline";
            var stamp=XaceCanonical.Parse(XaceCanonical.Text(message,"sync_json"));
            if (XaceCanonical.Text(stamp,"schema")!="xace.session_projection.v1" || stamp.Count!=9) throw new FormatException("Unsupported projection stamp");
            if(string.IsNullOrEmpty(XaceCanonical.Text(stamp,"baseline_id")))throw new FormatException("Missing baseline identity");
            foreach(string key in new[]{"session_id","authority_incarnation","ruleset_epoch"})
                if (XaceJson.Serialize(XaceCanonical.Get(stamp,key))!=XaceJson.Serialize(XaceCanonical.Get(epoch,key))) throw new FormatException("Projection identity mismatch");
            long generation=XaceCanonical.Integer(XaceCanonical.Get(stamp,"connection_generation"),1), seq=XaceCanonical.Integer(XaceCanonical.Get(stamp,"sequence"),1), tick=XaceCanonical.Integer(XaceCanonical.Get(stamp,"next_tick"),0);
            if (initial ? generation<=Generation : generation!=Generation || seq<=sequence) return "drop";
            if (!initial && !baseline && (Recovering || seq!=sequence+1 || tick!=NextTick+1)) { Recovering=true; return "recover"; }
            string raw=XaceCanonical.Text(message,"projection_json");
            var entities=XaceJson.DeserializeObject("{\"entities\":"+raw+"}")?["entities"] as List<object>;
            if (entities==null || XaceCanonical.Hash(raw)!=XaceCanonical.Text(stamp,"projection_digest"))
            { if(initial) throw new FormatException("Invalid initial projection"); Recovering=true; return "recover"; }
            XaceCanonical.ValidateEntities(entities);
            if (!initial && tick<NextTick) return "drop";
            if (initial)
            {
                foreach(string key in new[]{"session_id","authority_incarnation","ruleset_epoch"})
                    if(XaceJson.Serialize(XaceCanonical.Get(message,key))!=XaceJson.Serialize(XaceCanonical.Get(epoch,key)))throw new FormatException("Handshake identity mismatch");
                if(XaceCanonical.Text(message,"cgs_hash")!=cgsHash)throw new FormatException("Handshake source mismatch");
                long player=XaceCanonical.Integer(XaceCanonical.Get(message,"assigned_player_id"),1);
                if(XaceCanonical.Integer(XaceCanonical.Get(message,"assigned_peer_id"),1)!=PeerId || (PlayerId!=0 && player!=PlayerId)) throw new FormatException("Ownership changed");
                bool owned=false;
                foreach(var value in entities) { var entity=XaceCanonical.Object(value); if(XaceCanonical.Integer(XaceCanonical.Get(entity,"id"),1)!=player)continue;
                    var input=XaceCanonical.Parse(XaceCanonical.Text(XaceCanonical.Object(XaceCanonical.Get(entity,"components")),"6"));
                    owned=XaceCanonical.Integer(XaceCanonical.Get(input,"controller_id"),1)==ControllerId && XaceCanonical.Text(input,"control_type")=="HUMAN"; }
                if(!owned)throw new FormatException("Owned controller missing");
                World.Bind(XaceCanonical.Object(XaceCanonical.Get(message,"world_bindings")),entities);
                Credential=XaceCanonical.Text(message,"reconnect_credential"); if(Credential.Length==0)throw new FormatException("Missing reconnect credential"); PlayerId=player;
            }
            else if (!baseline && XaceCanonical.Integer(XaceCanonical.Get(message,"tick"),0)!=tick-1) throw new FormatException("Tick mismatch");
            message[initial?"initial_entities":"entities"]=entities; message["sync"]=stamp;
            Generation=generation; sequence=seq; NextTick=tick; Recovering=false; requestedTick=-1; sent=false;
            return "accept";
        }
        public bool Request(long tick)
        { if(Recovering || tick!=NextTick || requestedTick==tick)return false; requestedTick=tick;sent=false;return true; }
        public bool CanSend(long tick,long peer,long player) => !Recovering && !sent && requestedTick==tick && tick==NextTick && peer==PeerId && player==PlayerId;
        public void Sent() { sent=true; }
        public void Fence() { Recovering=true; requestedTick=-1; }
    }
}
