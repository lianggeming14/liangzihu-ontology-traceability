"""在 Windows 上用取证截图、中文本机语音和 FFmpeg 重建演示视频。"""
from __future__ import annotations

import argparse
import json
import math
import subprocess
import tempfile
import wave
from functools import lru_cache
from pathlib import Path

import imageio_ffmpeg
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps
import win32com.client

HERE = Path(__file__).resolve().parent
OUT = HERE.parent
FF = imageio_ffmpeg.get_ffmpeg_exe()
W, H, FPS = 1920, 1080, 24
PAPER, WHITE, INK = "#f2f3ed", "#ffffff", "#102f32"
MUTED, TEAL, MINT, RULE, GOLD = "#466260", "#075f5e", "#a4f2c8", "#bfd0c4", "#e8b262"
FONTDIR = Path("C:/Windows/Fonts")
STEPS = ["交接任务", "建立对象", "沿关系核查", "定位来源", "锁定版本", "交接结果"]
BOOK = json.loads((HERE / "视频分镜.json").read_text(encoding="utf-8-sig"))

@lru_cache(None)
def font(size, style="regular"):
    name = {"regular":"msyh.ttc", "bold":"msyhbd.ttc", "num":"bahnschrift.ttf",
            "mono":"consola.ttf"}[style]
    return ImageFont.truetype(str(FONTDIR / name), size)

def label(d, xy, value, size=30, fill=INK, style="regular"):
    d.text(xy, str(value), font=font(size,style), fill=fill, anchor="lt")

def bar(d, xy, fill=RULE, width=2):
    d.line(xy,fill=fill,width=width)

def fit_lines(d, text, size, width):
    lines,buf=[],""
    for char in text:
        if char=="\n" or (buf and d.textlength(buf+char,font=font(size))>width):
            lines.append(buf);buf=""
        if char!="\n": buf+=char
    if buf: lines.append(buf)
    return lines

def new_frame(phase, dark=False):
    im=Image.new("RGB",(W,H),INK if dark else PAPER);d=ImageDraw.Draw(im)
    c=MINT if dark else TEAL
    label(d,(66,41),"武昌鱼智慧养殖数据治理与溯源服务系统",27,WHITE if dark else INK,"bold")
    label(d,(66,84),"项目展示   /   实验室合成台账",20,c)
    x=928
    for i,word in enumerate(STEPS):
        bar(d,(x,45,x+131,45),c if i==phase else ("#435c5c" if dark else "#cbd4cc"),6 if i==phase else 2)
        label(d,(x,65),word,22,c if i==phase else ("#afc3bd" if dark else "#586a63"),"bold" if i==phase else "regular")
        x+=156
    bar(d,(66,123,1854,123),"#355558" if dark else RULE)
    return im,d

def subtitle(im, text):
    d=ImageDraw.Draw(im);d.rectangle((0,933,W,H),fill="#0c282b")
    d.rectangle((66,968,73,1030),fill=MINT)
    lines=fit_lines(d,text,37,1735)
    if len(lines)>2: raise ValueError("字幕超过两行："+text)
    y=990 if len(lines)==1 else 957
    for line in lines:
        label(d,(100,y),line,37,WHITE);y+=51

def header(d, title, sub):
    label(d,(66,159),title,61,INK,"bold")
    label(d,(69,245),sub,27,MUTED)

def note(d,x,y,head,detail, width=485):
    label(d,(x,y),head,26,TEAL,"bold")
    yy=y+48
    for s in fit_lines(d,detail,31,width):
        label(d,(x,yy),s,31,INK); yy+=48
    return yy

def ledger(d,x,y,width,rows):
    for key,val in rows:
        bar(d,(x,y,x+width,y),"#52716d",1)
        label(d,(x+4,y+21),key,23,"#c4d8d0")
        label(d,(x+202,y+17),val,32,WHITE,"bold")
        y+=84

def opening(d, ending=False):
    label(d,(70,194),"合作社批次交接   /   模拟案例",30,MINT,"bold")
    for y,t in zip((292,408),("这一批武昌鱼，","来自哪口塘？") if not ending else ("交接有了","可复查的答案。")):
        label(d,(62,y),t,95,WHITE,"bold")
    label(d,(70,615),"从一条鱼群记录，追到塘口、水质原行和版本。" if not ending else "试点拟用相同任务，对照核查正确率与交接耗时。",34,"#cedcd7")
    bar(d,(70,756,706,756),"#486966")
    label(d,(70,786),"对象关系  /  来源记录  /  数据版本",27,MINT)
    x=1025
    d.rounded_rectangle((x,183,1848,858),20,fill="#183e40",outline="#58837a",width=2)
    label(d,(x+43,231),"交接记录",32,MINT,"bold")
    label(d,(x+40,313),"C01",142,WHITE,"num")
    label(d,(x+48,479),"武昌鱼养殖鱼群",31,"#dcf0e6")
    rows=([("要查的塘口","哪一口？"),("要查的记录","哪一天？"),("交接依据","如何复核？")]
          if not ending else [("关联塘口","P01 · 1号模拟塘"),("观测时间","01月11日 06:00"),("原表位置","数据247 / 文件248行")])
    ledger(d,x+48,559,724,rows)

def table_inputs(d):
    header(d,"从四张业务表开始","一次交接涉及不同岗位维护的台账。对象标识和关系字段决定了它们怎样连接。")
    entries=[("01","鱼群","cohorts.csv","C01","鱼群标识"),
             ("02","入住事件","pond_cohort_occupancy.csv","OCC000001","入塘与离塘时间"),
             ("03","塘口","ponds.csv","P01","塘口标识"),
             ("04","水质观测","water_observations.csv","O1_010_06","观测标识")]
    for i,(num,name,filename,identifier,field) in enumerate(entries):
        y=322+i*132
        d.rounded_rectangle((68,y,1852,y+111),13,fill=WHITE)
        label(d,(103,y+33),num,35,TEAL,"num");label(d,(196,y+28),name,37,INK,"bold")
        label(d,(502,y+39),filename,30,MUTED,"mono")
        label(d,(1087,y+32),identifier,39,TEAL,"num");label(d,(1444,y+37),field,27,MUTED)

def relationship(d, progress):
    header(d,"对象之间，保留关系的含义","本例由共同的塘口和在塘时间关联到观测。图中箭头表示台账里可复查的指向。")
    nodes=[(72,486,403,666,"鱼群","C01"),(549,486,944,666,"入住事件","OCC000001"),
           (1092,486,1373,666,"塘口","P01"),(1508,486,1850,666,"水质观测","O1_010_06")]
    for i,(l,t,r,b,typ,code) in enumerate(nodes):
        d.rounded_rectangle((l,t,r,b),18,fill=INK if i==2 else WHITE,outline=TEAL if i==2 else RULE,width=2)
        label(d,(l+29,t+31),typ,30,MINT if i==2 else MUTED)
        label(d,(l+28,t+88),code,48 if len(code)>5 else 65,WHITE if i==2 else TEAL,"num")
    for a,b,rev,tag in [(403,549,True,"鱼群"),(944,1092,False,"塘口"),(1373,1508,True,"塘口")]:
        y=572;bar(d,(a,y,b,y),TEAL,5)
        p=a+5 if rev else b-5; inward=1 if rev else -1
        d.polygon([(p,y),(p+inward*17,y-11),(p+inward*17,y+11)],fill=TEAL)
        label(d,(a+38,y-47),tag,23,MUTED)
    label(d,(70,764),"核查路径",25,TEAL,"bold")
    label(d,(255,755),"从鱼群找入住事件，再经塘口找同一时段的观测。",36,INK)

SHOT_DETAILS = {
    "govern":("存量台账怎样进入交接流程","项目计划书的技术路线  /  画面取自 11 月 12 日运行的工作台","CSV / ZIP","数据准备","盘点表格、约定字段映射","版本交付","校验、发布、查询与导出"),
    "sphere":("从关系球看对象类型","本体关系球实景  /  六图发布快照","养殖批次","图上的点","对象类型","选中节点","亮起与它相连的关系"),
    "edge":("从一条边看实际关联","六图发布快照  /  已发布的实例关系聚合","pond_id","方向","养殖批次 → 塘口","实例关系","14 条"),
    "pair":("展开这条边，定位到一个实例对","六图发布快照  /  聚合关系钻取","C01 → P01","来源对象","C01 鱼群","目标对象","1 号模拟塘"),
    "fish":("打开鱼群对象","从对象标识开始查","C01","起养日期","2025 年 1 月 10 日","初始数量","6,000 尾"),
    "occupancy":("查看入住事件","用时间校验批次归属","OCC000001","入塘","01 月 10 日 10:00","离塘","11 月 20 日 14:00"),
    "pond":("沿关系进入塘口","从对象详情查看关联","P01","塘口名称","1 号模拟塘","台账面积","6,200 平方米"),
    "water":("找到在塘期间的水质观测","同一塘口 · 入住之后","O1_010_06","塘口","P01","观测时间","01 月 11 日 06:00"),
    "water_detail":("核对观测值与单位","同一观测记录的字段","O1_010_06","水温","11.13 ℃","溶解氧","6.72 mg/L"),
    "source":("回到原表的这一行","来源文件  /  csv/water_observations.csv","O1_010_06","原始行号","第 247 条数据","CSV 记录结束行","第 248 行"),
    "publish":("复查版本，再导出","历史运行界面  /  2026 年 11 月 12 日","d96f7ebf…","截图所选类型","现金分配","同版本下载核验","生产计划类 · 33 条三元组"),
    "click_a":("从入住记录跳转到塘口","原系统点击实录  /  五图审阅快照","P01","起点","入住事件 OCC000001","落点","1 号模拟塘"),
    "click_b":("从观测详情打开来源","原系统点击实录  /  五图审阅快照","O1_010_06","入口","塘口的入向关系","落点","观测对象的来源记录"),
}

def shot_base(d,key):
    title,sub,identifier,a,av,b,bv=SHOT_DETAILS[key]
    header(d,title,sub)
    d.rounded_rectangle((64,306,1342,904),14,fill=WHITE,outline=RULE,width=2)
    d.rounded_rectangle((1363,306,1854,904),14,fill="#e1ebe1")
    label(d,(1396,344),"核对字段",26,TEAL,"bold")
    identifier_style="num" if identifier.isascii() else "bold"
    label(d,(1393,410),identifier,56 if len(identifier)>4 else 77,TEAL,identifier_style)
    bar(d,(1397,511,1820,511),"#adc4b9")
    note(d,1398,552,a,av,width=412)
    note(d,1398,701,b,bv,width=412)

def edition(d):
    header(d,"把原包和读取版本一同固定","此处展示的五图审阅快照，与下列历史服务发布的导航清单逐字节一致。")
    d.rounded_rectangle((66,335,1828,557),19,fill=WHITE)
    label(d,(104,383),"输入包  /  SHA-256",30,TEAL,"bold")
    label(d,(105,451),"a4d78be79a83 … f799b4524",58,INK,"mono")
    d.rounded_rectangle((66,578,1828,817),19,fill="#dbe9de")
    label(d,(104,624),"发布版本  /  release_id",30,TEAL,"bold")
    label(d,(105,699),"d96f7ebf-c709-4ec0-a598-13927ef2b54e",51,INK,"mono")
    label(d,(70,860),"来源记录还保存了文件摘要与对象 IRI，完整值收录在截图取证清单。",26,MUTED)

def validate(d):
    header(d,"把验证结果和存疑记录一起交付","11 月 24 日冻结版本复测  /  专用 SQL 导入及全量回读  /  66 张业务表")
    for i,(value,unit,desc) in enumerate([("153,862","条业务记录","与规范实例逐项回读"),("810,934","条关系","其中 43 条保留未解析状态"),("95.283","秒","三轮专用导入的平均用时")]):
        x=68+i*596
        d.rounded_rectangle((x,350,x+565,727),16,fill=WHITE)
        label(d,(x+27,401),value,92,TEAL,"num")
        label(d,(x+30,537),unit,37,INK,"bold");bar(d,(x+30,623,x+531,623),RULE)
        label(d,(x+30,661),desc,24,MUTED)
    label(d,(70,806),"业务演示采用模拟台账。现场交接效果仍待授权试点验证。",30,MUTED)

def voice_clips(tmp):
    voice=win32com.client.Dispatch("SAPI.SpVoice")
    voice.Voice=next(v for v in voice.GetVoices() if "Huihui" in v.GetDescription())
    voice.Rate=1
    all_audio=[];counts=[]
    for i,shot in enumerate(BOOK):
        path=tmp/f"speech{i}.wav"
        stream=win32com.client.Dispatch("SAPI.SpFileStream")
        fmt=win32com.client.Dispatch("SAPI.SpAudioFormat");fmt.Type=22;stream.Format=fmt
        stream.Open(str(path),3,False);voice.AudioOutputStream=stream;voice.Speak(shot.get("voice",shot["subtitle"]));stream.Close()
        with wave.open(str(path)) as w:
            assert (w.getframerate(), w.getnchannels(),w.getsampwidth())==(22050,1,2)
            a=np.frombuffer(w.readframes(w.getnframes()),dtype="<i2")
        active=np.flatnonzero(np.abs(a.astype(np.int32))>130)
        if not len(active): raise RuntimeError("语音为空")
        a=a[max(0,active[0]-600):min(len(a),active[-1]+1500)]
        pad_begin=5512 if i==0 or BOOK[i-1]["view"]!=shot["view"] else 2205
        pad_end=6615 if i!=len(BOOK)-1 else 22050
        num=math.ceil((len(a)+pad_begin+pad_end)*FPS/22050)
        # Round cumulative sample targets so audio stays aligned to video frames.
        start_samples=round(sum(counts)*22050/FPS);end_samples=round((sum(counts)+num)*22050/FPS)
        all_audio.append(np.pad(a,(pad_begin,end_samples-start_samples-len(a)-pad_begin)));counts.append(num)
    with wave.open(str(tmp/"voice.wav"),"wb") as w:
        w.setparams((1,2,22050,0,"NONE","not compressed"));w.writeframes(np.concatenate(all_audio).astype("<i2").tobytes())
    return counts

def paste_capture(im, capture, rect, ease):
    # Fit the untouched frame first, then zoom to the selected native UI region.
    a=np.array((0,0,capture.width,capture.height),float);b=np.array(rect,float)*[capture.width,capture.height,capture.width,capture.height]
    box=tuple(np.round(a+(b-a)*ease).astype(int))
    cropped=capture.crop(box)
    vp=(1244,559); fitted=ImageOps.contain(cropped,vp,Image.Resampling.LANCZOS)
    im.paste(fitted,(81+(vp[0]-fitted.width)//2,325+(vp[1]-fitted.height)//2))

def compose(shot, media, progress=1):
    key=shot["view"];im,d=new_frame(shot["phase"],key in ("open","end"))
    if key in ("open","end"): opening(d,key=="end")
    elif key=="input":table_inputs(d)
    elif key=="map":relationship(d,progress)
    elif key=="version":edition(d)
    elif key=="validation":validate(d)
    elif key in ("click_a","click_b"):shot_base(d,key)
    else:
        shot_base(d,key); img,rect=media[key]
        paste_capture(im,img,rect,progress)
    subtitle(im,shot["subtitle"])
    return im

def native_action(tmp,index,shot,n,previous):
    key=shot["view"];prefix={"click_a":"动作A","click_b":"动作B"}[key]
    source=next((OUT/"系统截图").glob(prefix+"*.mp4"))
    bg=compose(shot,{},1);bg_path=tmp/f"native_bg{index}.png"; bg.save(bg_path)
    output=tmp/f"clip{index:02}.mp4"
    # The fixed UI frame is large enough to show the whole browser. Keep the
    # capture at its original pace, then hold its verified end state for narration.
    vf=f"[1:v]fps={FPS},scale=994:559,tpad=stop_mode=clone:stop_duration={n/FPS:.4f}[ui];[0:v][ui]overlay=206:325:shortest=1"
    run([FF,"-hide_banner","-loglevel","error","-y","-loop","1","-framerate",str(FPS),"-i",str(bg_path),"-i",str(source),
         "-filter_complex",vf,"-frames:v",str(n),"-an","-c:v","libx264","-threads","4","-preset","veryfast","-crf","18","-pix_fmt","yuv420p",str(output)])
    last=tmp/f"native_end{index}.png"
    run([FF,"-hide_banner","-loglevel","error","-y","-ss",str((n-2)/FPS),"-i",str(output),"-frames:v","1",str(last)])
    im=Image.open(last).convert("RGB");im.save(tmp/f"review-{index:02}.jpg",quality=88)
    return output,im

def run(cmd,**kwargs):
    return subprocess.run(cmd,check=True,**kwargs)

def make_video(tmp):
    spec=json.loads((HERE/"视频画面取景.json").read_text(encoding="utf-8-sig"))
    media={k:(Image.open(OUT/v["file"]).convert("RGB"),v.get("crop",[0,0,1,1])) for k,v in spec.items()}
    counts=voice_clips(tmp)
    segments=[];previous=None
    for i,(shot,n) in enumerate(zip(BOOK,counts)):
        key=shot["view"]
        if key in ("click_a","click_b"):
            seg,previous=native_action(tmp,i,shot,n,previous);segments.append(seg);continue
        final=compose(shot,media); start=compose(shot,media,0)
        final.save(tmp/f"review-{i:02}.jpg",quality=88)
        clip=tmp/f"clip{i:02}.mp4";segments.append(clip)
        # Animate a short dissolve and native crop, then hold so details can be read.
        moving = key in media and media[key][1] != [0,0,1,1]
        change=47 if moving else 9
        step_count=min(change,n)
        cmd=[FF,"-hide_banner","-loglevel","error","-y","-f","rawvideo","-pix_fmt","rgb24","-s",f"{W}x{H}","-r",str(FPS),"-i","-",
             "-vf",f"tpad=stop_mode=clone:stop={n-step_count}","-frames:v",str(n),"-c:v","libx264","-threads","4","-preset","veryfast","-tune","stillimage","-crf","19","-pix_fmt","yuv420p",str(clip)]
        proc=subprocess.Popen(cmd,stdin=subprocess.PIPE)
        for frame in range(step_count):
            if moving and frame>=9:
                amount=min(1,(frame-9)/(step_count-10));ease=amount*amount*(3-2*amount);im=compose(shot,media,ease)
            else: im=start if moving else final
            if previous is not None and frame<8: im=Image.blend(previous,im,(frame+1)/8)
            proc.stdin.write(im.tobytes())
        proc.stdin.close()
        if proc.wait(): raise RuntimeError("分镜编码失败")
        print(f"{i+1}/{len(BOOK)} {key} {n/FPS:.2f}s",flush=True);previous=final
    (tmp/"segments.txt").write_text("".join(f"file '{s.name}'\n" for s in segments),encoding="ascii")
    video=OUT/"武昌鱼项目展示.mp4"
    meta=[";FFMETADATA1","title=武昌鱼智慧养殖数据治理与溯源服务系统"]
    for phase,title in enumerate(STEPS):
        lo=next(i for i,shot in enumerate(BOOK) if shot["phase"]==phase)
        hi=max(i for i,shot in enumerate(BOOK) if shot["phase"]==phase)+1
        meta.extend(("[CHAPTER]",f"TIMEBASE=1/{FPS}",f"START={sum(counts[:lo])}",f"END={sum(counts[:hi])}",f"title={title}"))
    (tmp/"chapters.txt").write_text("\n".join(meta)+"\n",encoding="utf-8")
    run([FF,"-hide_banner","-loglevel","error","-y","-f","concat","-safe","0","-i",str(tmp/"segments.txt"),"-i",str(tmp/"voice.wav"),
         "-f","ffmetadata","-i",str(tmp/"chapters.txt"),"-map","0:v","-map","1:a","-map_metadata","2","-map_chapters","2",
         "-c:v","copy","-c:a","aac","-b:a","128k","-movflags","+faststart",str(video)])
    def stamp(fr):
        ms=round(fr*1000/FPS);s=ms//1000
        return f"{s//3600:02}:{s//60%60:02}:{s%60:02},{ms%1000:03}"
    at=0;sub=[]
    for i,(shot,n) in enumerate(zip(BOOK,counts)):
        sub.append(f"{i+1}\n{stamp(at)} --> {stamp(at+n)}\n{shot['subtitle']}\n\n");at+=n
    (HERE/"中文字幕.srt").write_text("".join(sub),encoding="utf-8-sig")
    print(f"{video.name}  {sum(counts)/FPS:.3f} s",flush=True)

if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work",type=Path,help="指定临时渲染目录，用于查看逐镜渲染检查图。")
    args=parser.parse_args()
    if args.work:
        args.work.mkdir(parents=True,exist_ok=True);make_video(args.work.resolve())
    else:
        with tempfile.TemporaryDirectory() as path: make_video(Path(path))
