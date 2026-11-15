"""Native CAD assembly views and same-scale size comparison; never a LUT master."""
from pathlib import Path
import subprocess, xml.etree.ElementTree as E, re
from PySide6.QtWidgets import QApplication
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtGui import QImage, QPainter
from PySide6.QtCore import Qt

ROOT=Path(__file__).resolve().parents[2]
CAD=ROOT/'hardware/v2-input/r53-compact-20261102'
OUT=CAD/'print'
WORK=ROOT/'build/analog-r53-compact'
CLI='D:/Programs/bin/kicad-cli.exe'
NS='http://www.w3.org/2000/svg'
E.register_namespace('',NS)

def export(board, path):
    subprocess.run([CLI,'pcb','export','svg','--layers','F.Fab,F.Silkscreen,Edge.Cuts',
        '--sketch-pads-on-fab-layers','--black-and-white','--exclude-drawing-sheet',
        '--mode-single','--page-size-mode','2','--output',str(path),str(board)],check=True)
    return E.parse(path).getroot()

def png(svg,path,width):
    renderer=QSvgRenderer(str(svg))
    size=renderer.defaultSize()
    assert renderer.isValid() and size.width()>0
    image=QImage(width,round(width*size.height()/size.width()),QImage.Format_ARGB32)
    image.fill(Qt.white)
    painter=QPainter(image);renderer.render(painter);painter.end()
    assert image.save(str(path))

def main():
    app=QApplication([])
    OUT.mkdir(exist_ok=True);WORK.mkdir(exist_ok=True)
    old=export(ROOT/'hardware/v2-input/r52-lut-20261102/analog-input-r52.kicad_pcb',WORK/'r52-assembly.svg')
    new=export(CAD/'analog-input-r53.kicad_pcb',OUT/'assembly-overview.svg')
    size=lambda node,key:float(re.sub('[a-zA-Z]+','',node.attrib[key]))
    # Native board-area SVG carries its own mm dimensions. Both nested maps
    # retain that common scale; no independent fit-to-box distortion is used.
    ow,oh=size(old,'width'),size(old,'height');nw,nh=size(new,'width'),size(new,'height')
    width=ow+nw+18;height=max(oh,nh)+33
    root=E.Element('{'+NS+'}svg',{'viewBox':f'0 0 {width} {height}','width':str(width*5),'height':str(height*5)})
    E.SubElement(root,'{'+NS+'}rect',{'width':'100%','height':'100%','fill':'white'})
    for node,x,label in [(old,4,'R5.2 — исходная компоновка'),(new,ow+13,'R5.3 — компактная')]:
        # QtSvg does not reliably render nested svg viewports. Both native
        # exports use mm coordinates starting at zero, so translate their
        # groups directly without changing the common physical scale.
        group=E.SubElement(root,'{'+NS+'}g',{'transform':f'translate({x},17)'})
        for child in list(node):group.append(child)
        E.SubElement(root,'{'+NS+'}text',{'x':str(x),'y':'9','font-family':'Arial','font-size':'3.1','fill':'#102a35'}).text=label
    E.SubElement(root,'{'+NS+'}text',{'x':'4','y':str(height-8),'font-family':'Arial','font-size':'2.7','fill':'#102a35'}).text='Одинаковый масштаб обоих видов. Это иллюстрация; шаблоны ЛУТ находятся в PDF.'
    target=OUT/'size-comparison.svg'
    E.ElementTree(root).write(target,encoding='utf-8',xml_declaration=True)
    png(target,OUT/'size-comparison.png',1800)
    png(OUT/'assembly-overview.svg',OUT/'assembly-overview.png',1600)

if __name__=='__main__':main()
