import os,sys,time,threading,subprocess,urllib.request,concurrent.futures as cf
url_file,out,size=sys.argv[1],sys.argv[2],int(sys.argv[3])
CH=64*1024*1024; W=16
def fresh_url():
    tok=subprocess.check_output(['gh','auth','token'],text=True).strip()
    r=subprocess.run(['curl','-s','-o','NUL','-w','%{redirect_url}','-H','Authorization: Bearer '+tok,'-H','Accept: application/vnd.github+json',
      'https://api.github.com/repos/scottconverse/civiccast-native/actions/artifacts/'+sys.argv[4]+'/zip'],capture_output=True,text=True)
    return r.stdout.strip()
url=[fresh_url()]; lock=threading.Lock(); done=[0]
with open(out,'wb') as f: f.truncate(size)
def get(i):
    s=i*CH; e=min(size-1,s+CH-1)
    for a in range(8):
        try:
            rq=urllib.request.Request(url[0],headers={'Range':f'bytes={s}-{e}'})
            d=urllib.request.urlopen(rq,timeout=120).read()
            if len(d)!=e-s+1: raise IOError('short')
            with lock:
                with open(out,'r+b') as f: f.seek(s); f.write(d)
                done[0]+=len(d)
            return
        except Exception as ex:
            if a==3:
                with lock: url[0]=fresh_url()
            time.sleep(2+a*3)
    raise SystemExit('chunk %d failed'%i)
n=(size+CH-1)//CH; t0=time.time()
def prog():
    while done[0]<size:
        time.sleep(60); print('%s %.2f/%.2f GB %.1f MB/s'%(time.strftime('%H:%M:%S'),done[0]/1e9,size/1e9,done[0]/1e6/(time.time()-t0)),flush=True)
threading.Thread(target=prog,daemon=True).start()
with cf.ThreadPoolExecutor(W) as ex: list(ex.map(get,range(n)))
print('PDL DONE',time.strftime('%H:%M:%S'),flush=True)
