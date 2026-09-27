import os

folder = r"D:\Coding\youtube\images"

files = sorted(os.listdir(folder))

num = 1

for file in files:
    if file.lower().endswith((".jpg", ".jpeg", ".png", ".gif", ".webp")):
        
        if file.startswith("img_"):
            continue

        ext = os.path.splitext(file)[1]

        while os.path.exists(os.path.join(folder, f"img_{num:02d}{ext}")):
            num += 1

        new_name = f"img_{num:02d}{ext}"

        os.rename(
            os.path.join(folder, file),
            os.path.join(folder, new_name)
        )

        num += 1