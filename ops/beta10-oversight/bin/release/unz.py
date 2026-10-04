import time
import zipfile

z = zipfile.ZipFile("zip/station.zip")
names = z.namelist()
print("entries", len(names), "first", names[:5], flush=True)
bad = z.testzip() if False else None
tot = sum(i.file_size for i in z.infolist())
done = 0
t = time.time()
for i in z.infolist():
    z.extract(i, "kit/station")
    done += i.file_size
    if i.file_size > 500e6:
        print(time.strftime("%H:%M:%S"), i.filename, i.file_size, flush=True)
print(f"UNZ DONE {tot / 1e9:.2f} GB {time.time() - t:.0f}s", flush=True)
