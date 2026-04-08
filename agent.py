import json,time,base64,re
from datetime import datetime
from google.oauth2 import service_account
from googleapiclient.discovery import build
F="credentials.json"
U="equipment@minimonstars.com"
SC=["https://www.googleapis.com/auth/gmail.readonly"]
MAIN="tracker_main.html"
SEEN="seen_ids.txt"
def load_seen():
    try: return set(open(SEEN).read().splitlines())
    except: return set()
def save_seen(s): open(SEEN,"w").writelines(x+"\n" for x in s)
def svc():
    c=service_account.Credentials.from_service_account_file(F,scopes=SC).with_subject(U)
    return build("gmail","v1",credentials=c)
def get_msg(s,mid):
    m=s.users().messages().get(userId="me",id=mid,format="full").execute()
    hdrs={h["name"]:h["value"] for h in m["payload"]["headers"]}
    body=""
    parts=m["payload"].get("parts",[])
    if parts:
        for p in parts:
            if p["mimeType"]=="text/plain":
                body=base64.urlsafe_b64decode(p["body"].get("data","")+" ==").decode("utf-8",errors="ignore")
                break
    else:
        body=base64.urlsafe_b64decode(m["payload"]["body"].get("data","")+" ==").decode("utf-8",errors="ignore")
    return hdrs.get("From",""),body
def parse(body):
    lines=[l.strip() for l in body.splitlines() if l.strip()]
    fr,to,st,items="","","",[]
    for line in lines:
        u=line.upper()
        if u.startswith("FROM:"): fr=line.split(":",1)[1].strip()
        elif u.startswith("TO:"): to=line.split(":",1)[1].strip()
        elif u.startswith("STATE:"): st=line.split(":",1)[1].strip().upper()
        else:
            m=re.match(r"^(\d+)\s+(.+)$",line)
            if m: items.append((int(m.group(1)),m.group(2).strip()))
    return fr,to,st,items
def load_data():
    html=open(MAIN).read()
    m1=re.search(r"var COACHES = (\[.*?\]);",html,re.DOTALL)
    m2=re.search(r"var xferHistory = (\[.*?\]);",html,re.DOTALL)
    return json.loads(m1.group(1)),json.loads(m2.group(1) if m2 else "[]"),html
def save_data(coaches,history,html):
    html2=re.sub(r"var COACHES = \[.*?\];","var COACHES = "+json.dumps(coaches,separators=(",",":"))+";",html,flags=re.DOTALL)
    html2=re.sub(r"var xferHistory = \[.*?\];","var xferHistory = "+json.dumps(history,separators=(",",":"))+";",html2,flags=re.DOTALL)
    open(MAIN,"w").write(html2)
    print("Tracker updated -",len(history),"transfers.")
def find_coach(coaches,name):
    nl=name.lower()
    for c in coaches:
        if c["name"].lower()==nl: return c
    for c in coaches:
        if nl in c["name"].lower(): return c
    return None
def get_item(coach,item_name):
    il=item_name.lower()
    for prog,items in coach["eq"].items():
        for i,entry in enumerate(items):
            ci=entry.rfind(":")
            ename=entry[:ci].strip().lower() if ci>-1 else entry.lower()
            qty_str=entry[ci+1:].strip() if ci>-1 else "0"
            m=re.match(r"^(\d+)",qty_str)
            qty=int(m.group(1)) if m else 0
            if ename==il or il in ename: return prog,i,entry[:ci].strip() if ci>-1 else entry,qty
    return None,None,None,0
def set_item(coach,prog,idx,name,qty):
    if qty<=0:
        coach["eq"][prog].pop(idx)
        if not coach["eq"][prog]: del coach["eq"][prog]
    else: coach["eq"][prog][idx]=name+":"+str(qty)
def apply_transfer(fr_name,to_name,st,items):
    coaches,history,html=load_data()
    fr=find_coach(coaches,fr_name)
    to=find_coach(coaches,to_name)
    is_stockroom=fr_name.lower()=="stockroom"
    if fr is None and not is_stockroom: print("FROM not found:",fr_name); return False
    if to is None: print("TO not found:",to_name); return False
    # Validate stock before making any changes
    if fr is not None and to_name.lower() != "stockroom":
        for qty,item_name in items:
            prog,idx,name,cur=get_item(fr,item_name)
            if prog is None or cur < qty:
                print("REJECTED: {} does not have enough {} (has {}, needs {})".format(fr_name,item_name,cur if prog else 0,qty))
                return False
    now=datetime.now().strftime("%d %b %Y %I:%M %p")
    for qty,item_name in items:
        if fr:
            prog,idx,name,cur=get_item(fr,item_name)
            if prog: set_item(fr,prog,idx,name,max(0,cur-qty))
        prog,idx,name,cur=get_item(to,item_name)
        if prog: set_item(to,prog,idx,name,cur+qty)
        else:
            if "Sports" not in to["eq"]: to["eq"]["Sports"]=[]
            to["eq"]["Sports"].append(item_name+":"+str(qty))
        history.insert(0,{"qty":qty,"item":item_name,"from":fr_name,"to":to_name,"prog":"Sports","state":st or "-","date":now})
    save_data(coaches,history,html)
    return True
def process(gs,mid,seen):
    if mid in seen: return
    seen.add(mid)
    save_seen(seen)
    sender,body=get_msg(gs,mid)
    print("Email from",sender)
    fr,to,st,items=parse(body)
    if fr and to and items:
        print("Transfer:",fr,"->",to)
        if apply_transfer(fr,to,st,items): print("Done.")
    else: print("Not a transfer - skipped")
if __name__=="__main__":
    gs=svc()
    seen=load_seen()
    print("Agent started. Checking every 30 seconds...")
    while True:
        try:
            results=gs.users().messages().list(userId="me",labelIds=["INBOX"],maxResults=10).execute()
            for m in results.get("messages",[]): process(gs,m["id"],seen)
        except Exception as e: print("Error:",e)
        time.sleep(30)
