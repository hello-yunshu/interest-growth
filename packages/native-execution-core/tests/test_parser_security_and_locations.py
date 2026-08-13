from pathlib import Path
import zipfile,pytest

from interest_growth_native.parsing import NativeDocumentParser,ParserLimits
from interest_growth_native.errors import ResourceLimitError

def test_text_parser_enforces_input_size(tmp_path):
    p=tmp_path/"x.txt";p.write_bytes(b"a"*20)
    parser=NativeDocumentParser(ParserLimits(max_file_bytes=10))
    with pytest.raises(ResourceLimitError):parser.parse(p)

def test_pptx_slides_use_natural_numeric_order_and_locators(tmp_path):
    p=tmp_path/"x.pptx"
    xml=lambda text:f'<p:sld xmlns:p="x"><a:t xmlns:a="y">{text}</a:t></p:sld>'.encode()
    with zipfile.ZipFile(p,"w") as z:
        z.writestr("ppt/slides/slide10.xml",xml("ten"))
        z.writestr("ppt/slides/slide2.xml",xml("two"))
        z.writestr("ppt/slides/slide1.xml",xml("one"))
    out=NativeDocumentParser().parse(p)
    assert [x.locator.slide for x in out.sections]==[1,2,10]
    assert [x.text for x in out.sections]==["one","two","ten"]

def test_ooxml_archive_member_count_is_bounded(tmp_path):
    p=tmp_path/"x.docx"
    with zipfile.ZipFile(p,"w") as z:
        z.writestr("word/document.xml",b"<x/>")
        z.writestr("a",b"")
        z.writestr("b",b"")
    parser=NativeDocumentParser(ParserLimits(max_archive_members=2))
    with pytest.raises(ResourceLimitError):parser.parse(p)
