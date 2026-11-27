import certifi

with open("russian_root_ca.pem", "r", encoding="utf-8") as f:
    src = f.read()

with open("russian_sub_ca.pem", "r", encoding="utf-8") as f:
    sub = f.read()

path = certifi.where()
with open(path, "a", encoding="utf-8") as f:
    f.write("\n" + src + "\n" + sub + "\n")

print("added to", path)