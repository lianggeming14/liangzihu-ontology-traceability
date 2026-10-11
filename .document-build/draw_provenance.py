from PIL import Image,ImageDraw,ImageFont
from pathlib import Path
import math
BASE=Path(__file__).resolve().parent;FONT='C:/Windows/Fonts/msyh.ttc'
im=Image.new('RGB',(1600,880),'white');d=ImageDraw.Draw(im)
boxes=[(40,60,480,230,'原始证据','报文 图像区域 报告段落'),(580,60,1020,230,'处理与映射运行','方法 参数 版本 身份映射'),(1120,60,1560,230,'标准记录','观测 事件 来源陈述'),(40,480,480,670,'适用知识与规则','机制 条件 领域依据'),(580,480,1020,670,'推理运行','实际前提 规则 快照'),(1120,480,1560,670,'候选解释','支持 反证 替代解释 缺失')]
for x1,y1,x2,y2,a,b in boxes:
 d.rounded_rectangle((x1,y1,x2,y2),radius=10,fill='#F2F6F9',outline='#758694',width=2)
 for txt,y,size in [(a,y1+32,37),(b,y1+102,25)]:
  f=ImageFont.truetype(FONT,size);bb=d.textbbox((0,0),txt,font=f);d.text(((x1+x2-bb[2])/2,y),txt,font=f,fill='#17212B')
def arrow(x1,y1,x2,y2,label,lx,ly):
 d.line((x1,y1,x2,y2),fill='#455A64',width=4);a=math.atan2(y2-y1,x2-x1);s=15;d.polygon([(x2,y2),(x2-s*math.cos(a-.6),y2-s*math.sin(a-.6)),(x2-s*math.cos(a+.6),y2-s*math.sin(a+.6))],fill='#455A64');d.text((lx,ly),label,font=ImageFont.truetype(FONT,25),fill='#283640')
arrow(485,145,570,145,'输入',494,94);arrow(1025,145,1110,145,'生成',1034,94)
arrow(485,575,570,575,'适用',494,524);arrow(1025,575,1110,575,'产生',1034,524)
arrow(1250,240,900,470,'采用前提',940,322)
arrow(1340,475,1340,240,'解释对象',1370,342)
d.text((55,750),'来源链回答从哪里来  依据链回答如何得出  成因分析检验现实中的可能原因',font=ImageFont.truetype(FONT,29),fill='#283640')
d.text((55,815),'支持或反驳关系也记录评估方法与版本  新证据可触发重新评估',font=ImageFont.truetype(FONT,28),fill='#283640')
im.save(BASE/'provenance.png')
