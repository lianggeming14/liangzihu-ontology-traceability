from PIL import Image, ImageDraw, ImageFont
from pathlib import Path
import math
BASE=Path(__file__).resolve().parent
FONT='C:/Windows/Fonts/msyh.ttc'
def make(name,size):
 im=Image.new('RGB',size,'white'); return im,ImageDraw.Draw(im)
def box(d,rect,title,lines,fs=31):
 x1,y1,x2,y2=rect; d.rounded_rectangle(rect,radius=10,fill='#F2F6F9',outline='#758694',width=2)
 for i,txt in enumerate([title]+lines):
  font=ImageFont.truetype(FONT,fs if i==0 else fs-6); bb=d.textbbox((0,0),txt,font=font)
  d.text(((x1+x2-(bb[2]-bb[0]))/2,y1+18+i*(fs+10)),txt,font=font,fill='#17212B')
def arrow(d,x1,y1,x2,y2,label='',lx=0,ly=0):
 d.line((x1,y1,x2,y2),fill='#455A64',width=4); a=math.atan2(y2-y1,x2-x1); s=15
 d.polygon([(x2,y2),(x2-s*math.cos(a-.6),y2-s*math.sin(a-.6)),(x2-s*math.cos(a+.6),y2-s*math.sin(a+.6))],fill='#455A64')
 if label:d.text((lx,ly),label,font=ImageFont.truetype(FONT,25),fill='#283640')
im,d=make('architecture',(1600,1080))
box(d,(45,35,1555,155),'多源输入与已有业务事实',['传感器 视频 遥感 气象 文档 手工记录 库存和质量事件'],36)
arrow(d,800,160,800,206)
box(d,(45,212,1555,352),'来源登记与标准化处理',['原始材料保存  身份映射  单位时空对齐  候选校验  冲突与复核'],36)
arrow(d,800,357,800,403)
box(d,(45,410,1555,565),'权威业务库与本体证据库',['PostgreSQL  稳定身份  领域包  限定关系  事件与物料  断言与证据','私有资产保存原始材料  图与 RDF 是可重建投影'],35)
arrow(d,800,570,800,618)
box(d,(45,625,1555,770),'受控数据服务与变更通知',['按当前权限构建信息包  快照与版本  outbox 重放  发布与撤回检查'],36)
arrow(d,800,775,800,827)
d.line((265,827,1340,827),fill='#455A64',width=4)
for x in [265,800,1340]:arrow(d,x,827,x,867)
box(d,(45,875,485,1025),'代码推理层',['EvidenceBundle','实际前提与解释'],32)
box(d,(580,875,1020,1025),'企业溯源工作台',['TraceabilityBundle','物料谱系与质量依据'],32)
box(d,(1115,875,1555,1025),'消费者公开查询',['已审白名单发布','当前撤回与召回状态'],32)
im.save(BASE/'architecture.png')
im,d=make('traceability',(1600,880))
box(d,(40,55,480,230),'原平台业务服务',['生产 库存 检测 放行','事务内登记事件和凭证'],32)
box(d,(580,55,1020,230),'本体与证据服务',['身份 事件 关系 校验','保存来源与采用版本'],32)
box(d,(1120,55,1560,230),'溯源内容快照',['物料谱系 质量依据','缺口 范围 版本 哈希'],32)
arrow(d,485,145,570,145,'接入',493,92);arrow(d,1025,145,1110,145,'供数',1033,92)
arrow(d,1340,240,1340,438,'审核并发布',1380,320)
box(d,(1120,450,1560,645),'发布与状态服务',['白名单 权限 公开码','当前撤回 召回 检查'],32)
box(d,(580,450,1020,645),'受众查询与应用',['企业 合作方 消费者','各自读取获准的数据'],32)
box(d,(40,450,480,645),'补录与纠错请求',['回到业务服务或候选区','审核后形成新版本'],32)
arrow(d,1110,540,1025,540,'查询',1033,487);arrow(d,570,540,485,540,'反馈',493,487)
arrow(d,260,440,260,240,'业务校验',300,320)
d.text((60,722),'冻结内容保留历史  当前状态每次核验  证据撤回不删除实际物料流转事件',font=ImageFont.truetype(FONT,30),fill='#283640')
d.text((60,790),'更正和召回通过变更事件触发重算 发布审核 缓存失效及消费回执',font=ImageFont.truetype(FONT,30),fill='#283640')
im.save(BASE/'traceability.png')
