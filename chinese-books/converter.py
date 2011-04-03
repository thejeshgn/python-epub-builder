#!/usr/bin/env python2
import sys, os.path
from pdfdevice import PDFDevice, PDFTextDevice
from pdffont import PDFUnicodeNotDefined
from pdftypes import LITERALS_DCT_DECODE
from pdfcolor import LITERAL_DEVICE_GRAY, LITERAL_DEVICE_RGB
from layout import LTContainer, LTPage, LTText, LTLine, LTRect, LTPolygon
from layout import LTFigure, LTImage, LTChar, LTTextLine
from layout import LTTextBox, LTTextBoxVertical, LTTextGroup
from utils import apply_matrix_pt, mult_matrix
from utils import enc, bbox2str, create_bmp


##  PDFLayoutAnalyzer
##
class PDFLayoutAnalyzer(PDFTextDevice):

    def __init__(self, rsrcmgr, pageno=1, laparams=None):
        PDFTextDevice.__init__(self, rsrcmgr)
        self.laparams = laparams
        self.pageno = pageno
        self.stack = []
        return

    def begin_page(self, page, ctm):
        (x0,y0,x1,y1) = page.mediabox
        (x0,y0) = apply_matrix_pt(ctm, (x0,y0))
        (x1,y1) = apply_matrix_pt(ctm, (x1,y1))
        mediabox = (0, 0, abs(x0-x1), abs(y0-y1))
        self.cur_item = LTPage(self.pageno, mediabox)
        return

    def end_page(self, page):
        assert not self.stack
        assert isinstance(self.cur_item, LTPage)
        if self.laparams is not None:
            self.cur_item.analyze(self.laparams)
        self.pageno += 1
        self.receive_layout(self.cur_item)
        return

    def begin_figure(self, name, bbox, matrix):
        self.stack.append(self.cur_item)
        self.cur_item = LTFigure(name, bbox, mult_matrix(matrix, self.ctm))
        return

    def end_figure(self, _):
        fig = self.cur_item
        assert isinstance(self.cur_item, LTFigure)
        if self.laparams is not None:
            self.cur_item.analyze(self.laparams)
        self.cur_item = self.stack.pop()
        self.cur_item.add(fig)
        return

    def render_image(self, name, stream):
        assert isinstance(self.cur_item, LTFigure)
        item = LTImage(name, stream,
                       (self.cur_item.x0, self.cur_item.y0,
                        self.cur_item.x1, self.cur_item.y1))
        self.cur_item.add(item)
        return

    def paint_path(self, gstate, stroke, fill, evenodd, path):
        shape = ''.join(x[0] for x in path)
        if shape == 'ml':
            # horizontal/vertical line
            (_,x0,y0) = path[0]
            (_,x1,y1) = path[1]
            (x0,y0) = apply_matrix_pt(self.ctm, (x0,y0))
            (x1,y1) = apply_matrix_pt(self.ctm, (x1,y1))
            self.cur_item.add(LTLine(gstate.linewidth, (x0,y0), (x1,y1)))
        elif shape == 'mlllh':
            # rectangle
            (_,x0,y0) = path[0]
            (_,x1,y1) = path[1]
            (_,x2,y2) = path[2]
            (_,x3,y3) = path[3]
            (x0,y0) = apply_matrix_pt(self.ctm, (x0,y0))
            (x1,y1) = apply_matrix_pt(self.ctm, (x1,y1))
            (x2,y2) = apply_matrix_pt(self.ctm, (x2,y2))
            (x3,y3) = apply_matrix_pt(self.ctm, (x3,y3))
            if ((x0 == x1 and y1 == y2 and x2 == x3 and y3 == y0) or
                (y0 == y1 and x1 == x2 and y2 == y3 and x3 == x0)):
                self.cur_item.add(LTRect(gstate.linewidth, (x0,y0,x2,y2)))
        else:
            # other polygon
            pts = []
            for p in path:
                for i in xrange(1, len(p), 2):
                    pts.append(apply_matrix_pt(self.ctm, (p[i], p[i+1])))
            self.cur_item.add(LTPolygon(gstate.linewidth, pts))
        return

    def render_char(self, matrix, font, fontsize, scaling, rise, cid, text=None):
        if not text:
            try:
                text = font.to_unichr(cid)
                assert isinstance(text, unicode), text
            except PDFUnicodeNotDefined:
                text = self.handle_undefined_char(font, cid)
        textwidth = font.char_width(cid)
        textdisp = font.char_disp(cid)
        item = LTChar(matrix, font, fontsize, scaling, rise, text, textwidth, textdisp)
        self.cur_item.add(item)
        return item.adv

    def handle_undefined_char(self, font, cid):
        if self.debug:
            print >>sys.stderr, 'undefined: %r, %r' % (font, cid)
        return '\\x%X' % cid

    def receive_layout(self, ltpage):
        return


##  PDFPageAggregator
##
class PDFPageAggregator(PDFLayoutAnalyzer):

    def __init__(self, rsrcmgr, pageno=1, laparams=None):
        PDFLayoutAnalyzer.__init__(self, rsrcmgr, pageno=pageno, laparams=laparams)
        self.result = None
        return
    
    def receive_layout(self, ltpage):
        self.result = ltpage
        return

    def get_result(self):
        return self.result


##  PDFConverter
##
class PDFConverter(PDFLayoutAnalyzer):

    def __init__(self, rsrcmgr, outfp, codec='utf-8', pageno=1, laparams=None):
        PDFLayoutAnalyzer.__init__(self, rsrcmgr, pageno=pageno, laparams=laparams)
        self.outfp = outfp
        self.codec = codec
        return

    def write_image(self, image):
        stream = image.stream
        filters = stream.get_filters()
        if len(filters) == 1 and filters[0] in LITERALS_DCT_DECODE:
            ext = '.jpg'
            data = stream.get_rawdata()
        elif stream.colorspace is LITERAL_DEVICE_RGB:
            ext = '.bmp'
            data = create_bmp(stream.get_data(), stream.bits*3, image.width, image.height)
        elif stream.colorspace is LITERAL_DEVICE_GRAY:
            ext = '.bmp'
            data = create_bmp(stream.get_data(), stream.bits, image.width, image.height)
        else:
            ext = '.img'
            data = stream.get_data()
        name = image.name+ext
        path = os.path.join(self.outdir, name)
        fp = file(path, 'wb')
        fp.write(data)
        fp.close()
        return name
    

##  TextConverter
##
class TextConverter(PDFConverter):

    def __init__(self, rsrcmgr, outfp, codec='utf-8', pageno=1, laparams=None,
                 showpageno=False):
        PDFConverter.__init__(self, rsrcmgr, outfp, codec=codec, pageno=pageno, laparams=laparams)
        self.showpageno = showpageno
        return

    def write_text(self, text):
        self.outfp.write(text.encode(self.codec, 'ignore'))
        return

    def receive_layout(self, ltpage):
        def render(item):
            if isinstance(item, LTContainer):
                for child in item:
                    render(child)
            elif isinstance(item, LTText):
                self.write_text(item.text)
            if isinstance(item, LTTextBox):
                self.write_text('\n')
        if self.showpageno:
            self.write_text('Page %s\n' % ltpage.pageid)
        render(ltpage)
        self.write_text('\f')
        return


##  HTMLConverter
##
class HTMLConverter(PDFConverter):

    RECT_COLORS = {
        #'char': 'green',
        #'figure': 'yellow',
        #'textline': 'magenta',
        #'textbox': 'cyan',
        #'textgroup': 'red',
        'polygon': 'black',
        'page': 'gray',
        }
    TEXT_COLORS = {
        #'textbox': 'blue',
        'char': 'black',
        }

    def __init__(self, rsrcmgr, outfp, codec='utf-8', pageno=1, laparams=None, 
                 scale=1, fontscale=0.7, layoutmode='normal', showpageno=True, pagemargin=50,
                 outdir=None):
        PDFConverter.__init__(self, rsrcmgr, outfp, codec=codec, pageno=pageno, laparams=laparams)
        self.scale = scale
        self.fontscale = fontscale
        self.layoutmode = layoutmode
        self.showpageno = showpageno
        self.pagemargin = pagemargin
        self.outdir = outdir
        self.yoffset = self.pagemargin
        self._font = None
        self._fontstack = []
        self.write_header()
        return

    def write(self, text):
        self.outfp.write(text)
        return

    def write_header(self):
        self.write('<html><head>\n')
        self.write('<meta http-equiv="Content-Type" content="text/html; charset=%s">\n' % self.codec)
        self.write('</head><body>\n')
        return

    def write_footer(self):
        self.write('<div style="position:absolute; top:0px;">Page: %s</div>\n' %
                   ', '.join('<a href="#%s">%s</a>' % (i,i) for i in xrange(1,self.pageno)))
        self.write('</body></html>\n')
        return

    def write_text(self, text):
        self.write(enc(text, self.codec))
        return

    def place_rect(self, color, borderwidth, x, y, w, h):
        color = self.RECT_COLORS.get(color)
        if color is not None:
            self.write('<span style="position:absolute; border: %s %dpx solid; '
                       'left:%dpx; top:%dpx; width:%dpx; height:%dpx;"></span>\n' %
                       (color, borderwidth,
                        x*self.scale, (self.yoffset-y)*self.scale,
                        w*self.scale, h*self.scale))
        return

    def place_image(self, item, borderwidth, x, y, w, h):
        if self.outdir is not None:
            name = self.write_image(item)
            self.write('<img src="%s" border="%d" style="position:absolute; left:%dpx; top:%dpx;" '
                       'width="%d" height="%d" />\n' %
                       (enc(name), borderwidth,
                        x*self.scale, (self.yoffset-y)*self.scale,
                        w*self.scale, h*self.scale))
        return

    def place_text(self, color, text, x, y, size):
        color = self.TEXT_COLORS.get(color)
        if color is not None:
            self.write('<span style="position:absolute; color:%s; left:%dpx; top:%dpx; font-size:%dpx;">' %
                       (color, x*self.scale, (self.yoffset-y)*self.scale, size*self.scale*self.fontscale))
            self.write_text(text)
            self.write('</span>\n')
        return

    def begin_textbox(self, color, borderwidth, x, y, w, h, writing_mode):
        self._fontstack.append(self._font)
        self._font = None
        self.write('<div style="position:absolute; border: %s %dpx solid; writing-mode:%s; '
                   'left:%dpx; top:%dpx; width:%dpx; height:%dpx;">' %
                   (color, borderwidth, writing_mode,
                    x*self.scale, (self.yoffset-y)*self.scale,
                    w*self.scale, h*self.scale))
        return
    
    def put_text(self, text, fontname, fontsize):
        font = (fontname, fontsize)
        if font != self._font:
            if self._font is not None:
                self.write('</span>')
            self.write('<span style="font-family: %s; font-size:%dpx">' %
                       (fontname, fontsize * self.scale * self.fontscale))
            self._font = font
        self.write_text(text)
        return

    def put_newline(self):
        self.write('<br>')
        return

    def end_textbox(self, color):
        if self._font is not None:
            self.write('</span>')
        self._font = self._fontstack.pop()
        self.write('</div>')
        return

    def receive_layout(self, ltpage):
        def render(item):
            if isinstance(item, LTPage):
                self.yoffset += item.y1
                self.place_rect('page', 1, item.x0, item.y1, item.width, item.height)
                if self.showpageno:
                    self.write('<div style="position:absolute; top:%dpx;">' %
                               ((self.yoffset-item.y1)*self.scale))
                    self.write('<a name="%s">Page %s</a></div>\n' % (item.pageid, item.pageid))
                for child in item:
                    render(child)
            elif isinstance(item, LTPolygon):
                self.place_rect('polygon', 1, item.x0, item.y1, item.width, item.height)
            elif isinstance(item, LTFigure):
                self.place_rect('figure', 1, item.x0, item.y1, item.width, item.height)
                for child in item:
                    render(child)
            elif isinstance(item, LTImage):
                self.place_image(item, 1, item.x0, item.y1, item.width, item.height)
            else:
                if self.layoutmode == 'exact':
                    if isinstance(item, LTTextLine):
                        self.place_rect('textline', 1, item.x0, item.y1, item.width, item.height)
                        for child in item:
                            render(child)
                    elif isinstance(item, LTTextBox):
                        self.place_rect('textbox', 1, item.x0, item.y1, item.width, item.height)
                        self.place_text('textbox', str(item.index+1), item.x0, item.y1, 20)
                        for child in item:
                            render(child)
                    elif isinstance(item, LTChar):
                        self.place_rect('char', 1, item.x0, item.y1, item.width, item.height)
                        self.place_text('char', item.text, item.x0, item.y1, item.size)
                else:
                    if isinstance(item, LTTextLine):
                        for child in item:
                            render(child)
                        if self.layoutmode != 'loose':
                            self.put_newline()
                    elif isinstance(item, LTTextBox):
                        self.begin_textbox('textbox', 1, item.x0, item.y1, item.width, item.height,
                                           item.get_writing_mode())
                        for child in item:
                            render(child)
                        self.end_textbox('textbox')
                    elif isinstance(item, LTChar):
                        self.put_text(item.text, item.fontname, item.size)
                    elif isinstance(item, LTText):
                        self.write_text(item.text)
            return
        render(ltpage)
        if ltpage.layout:
            def show_layout(item):
                if isinstance(item, LTTextGroup):
                    self.place_rect('textgroup', 1, item.x0, item.y1, item.width, item.height)
                    for child in item:
                        show_layout(child)
                return
            show_layout(ltpage.layout)
        self.yoffset += self.pagemargin
        return

    def close(self):
        self.write_footer()
        return


##  XMLConverter
##
class XMLConverter(PDFConverter):

    def __init__(self, rsrcmgr, outfp, codec='utf-8', pageno=1, laparams=None, outdir=None):
        PDFConverter.__init__(self, rsrcmgr, outfp, codec=codec, pageno=pageno, laparams=laparams)
        self.outdir = outdir
        self.write_header()
        return

    def write_header(self):
        self.outfp.write('<?xml version="1.0" encoding="%s" ?>\n' % self.codec)
        self.outfp.write('<pages>\n')
        return

    def write_footer(self):
        self.outfp.write('</pages>\n')
        return
    
    def write_text(self, text):
        self.outfp.write(enc(text, self.codec))
        return

    def receive_layout(self, ltpage):
        def render(item):
            if isinstance(item, LTPage):
                self.outfp.write('<page id="%s" bbox="%s" rotate="%d">\n' %
                                 (item.pageid, bbox2str(item.bbox), item.rotate))
                for child in item:
                    render(child)
                self.outfp.write('</page>\n')
            elif isinstance(item, LTLine):
                self.outfp.write('<line linewidth="%d" bbox="%s" />\n' %
                                 (item.linewidth, bbox2str(item.bbox)))
            elif isinstance(item, LTRect):
                self.outfp.write('<rect linewidth="%d" bbox="%s" />\n' %
                                 (item.linewidth, bbox2str(item.bbox)))
            elif isinstance(item, LTPolygon):
                self.outfp.write('<polygon linewidth="%d" bbox="%s" pts="%s"/>\n' %
                                 (item.linewidth, bbox2str(item.bbox), item.get_pts()))
            elif isinstance(item, LTFigure):
                self.outfp.write('<figure name="%s" bbox="%s">\n' %
                                 (item.name, bbox2str(item.bbox)))
                for child in item:
                    render(child)
                self.outfp.write('</figure>\n')
            elif isinstance(item, LTTextLine):
                self.outfp.write('<textline bbox="%s">\n' % bbox2str(item.bbox))
                for child in item:
                    render(child)
                self.outfp.write('</textline>\n')
            elif isinstance(item, LTTextBox):
                wmode = ''
                if isinstance(item, LTTextBoxVertical):
                    wmode = ' wmode="vertical"'
                self.outfp.write('<textbox id="%d" bbox="%s"%s>\n' % (item.index, bbox2str(item.bbox), wmode))
                for child in item:
                    render(child)
                self.outfp.write('</textbox>\n')
            elif isinstance(item, LTChar):
                self.outfp.write('<text font="%s" bbox="%s" size="%.3f">' %
                                 (enc(item.fontname), bbox2str(item.bbox), item.size))
                self.write_text(item.text)
                self.outfp.write('</text>\n')
            elif isinstance(item, LTText):
                self.outfp.write('<text>%s</text>\n' % item.text)
            elif isinstance(item, LTImage):
                if self.outdir:
                    name = self.write_image(item)
                    self.outfp.write('<image src="%s" width="%d" height="%d" />\n' %
                                     (enc(name), item.width, item.height))
                else:
                    self.outfp.write('<image width="%d" height="%d" />\n' %
                                     (item.width, item.height))
            else:
                assert 0, item
            return
        def show_layout(item):
            if isinstance(item, LTTextBox):
                self.outfp.write('<textbox id="%d" bbox="%s" />\n' % (item.index, bbox2str(item.bbox)))
            elif isinstance(item, LTTextGroup):
                self.outfp.write('<textgroup bbox="%s">\n' % bbox2str(item.bbox))
                for child in item:
                    show_layout(child)
                self.outfp.write('</textgroup>\n')
            return
        render(ltpage)
        if ltpage.layout:
            self.outfp.write('<layout>\n')
            show_layout(ltpage.layout)
            self.outfp.write('</layout>\n')
        return

    def close(self):
        self.write_footer()
        return
