from pymongo import MongoClient
from pymongo.server_api import ServerApi
import socket
import dns.resolver

# ============================================
# FIX DNS - Bypass /etc/resolv.conf issue
# ============================================

def resolve_with_google_dns(hostname):
    try:
        resolver = dns.resolver.Resolver()
        resolver.nameservers = ['8.8.8.8', '1.1.1.1']
        answers = resolver.resolve(hostname, 'A')
        return answers[0].address
    except:
        return None

# Override DNS resolution
original_getaddrinfo = socket.getaddrinfo

def custom_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    if 'mongodb.net' in host or 'soto0pe' in host:
        ip = resolve_with_google_dns(host)
        if ip:
            print(f"✅ DNS: {host} → {ip}")
            return original_getaddrinfo(ip, port, family, type, proto, flags)
    return original_getaddrinfo(host, port, family, type, proto, flags)

socket.getaddrinfo = custom_getaddrinfo

# ============================================
# YOUR CREDENTIALS - UPDATE THESE!
# ============================================

USERNAME = "kl29royal"
PASSWORD = "MongoDB123"  # ← CHANGE to your actual password after reset

# ============================================
# CONNECTION
# ============================================

uri = f"mongodb://{USERNAME}:{PASSWORD}@ac-rx3qbmj-shard-00-00.soto0pe.mongodb.net:27017,ac-rx3qbmj-shard-00-01.soto0pe.mongodb.net:27017,ac-rx3qbmj-shard-00-02.soto0pe.mongodb.net:27017/?ssl=true&replicaSet=atlas-vudrpg-shard-0&authSource=admin&appName=Cluster0"

print("🔍 Connecting to MongoDB Atlas...")
print(f"👤 User: {USERNAME}")

try:
    client = MongoClient(uri, server_api=ServerApi('1'), serverSelectionTimeoutMS=10000)
    client.admin.command('ping')
    print("✅ CONNECTED SUCCESSFULLY!")
    print(f"📊 MongoDB Version: {client.server_info()['version']}")
    
    # List databases
    databases = client.list_database_names()
    print(f"📁 Databases: {databases}")
    
    # List collections in first database
    if databases:
        db = client[databases[0]]
        collections = db.list_collection_names()
        print(f"📂 Collections in '{databases[0]}': {collections}")
    
except Exception as e:
    print(f"❌ Connection failed: {e}")
    print("\n" + "="*50)
    print("TROUBLESHOOTING:")
    print("="*50)
    print("1. Go to https://cloud.mongodb.com")
    print("2. Database Access → kl29royal → Edit")
    print("3. Set password to: MongoDB123")
    print("4. Click Update User")
    print("5. Wait 30 seconds")
    print("6. Update PASSWORD in this script to: MongoDB123")
    print("7. Run again")
