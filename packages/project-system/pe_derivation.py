"""Strict PE certificate-append derivation, independent of certificate trust."""
import hashlib,struct
from authoring_identity import require

def layout(raw):
    require(type(raw) is bytes and 256<=len(raw)<=128*1024*1024 and raw[:2]==b'MZ','Windows PE bytes required')
    pe=struct.unpack_from('<I',raw,0x3c)[0]
    require(64<=pe and pe+24+152<=len(raw) and raw[pe:pe+4]==b'PE\0\0','Invalid PE header')
    require(struct.unpack_from('<H',raw,pe+4)[0]==0x8664,'AMD64 PE required')
    optional=pe+24;size=struct.unpack_from('<H',raw,pe+20)[0]
    require(size>=152 and optional+size<=len(raw) and struct.unpack_from('<H',raw,optional)[0]==0x20b,'PE32+ optional header required')
    require(struct.unpack_from('<I',raw,optional+108)[0]>=5,'PE security directory required')
    return optional+64,optional+112+4*8

def unsigned_identity(raw):
    checksum,security=layout(raw)
    require(raw[security:security+8]==b'\0'*8,'Original build must be unsigned')
    return len(raw),struct.unpack_from('<I',raw,checksum)[0]

def verify(raw,*,unsigned_sha256,unsigned_length,unsigned_pe_checksum):
    checksum,security=layout(raw)
    require(type(unsigned_length) is int and security+8<=unsigned_length<=len(raw),'Invalid unsigned PE length')
    require(type(unsigned_pe_checksum) is int and 0<=unsigned_pe_checksum<=0xffffffff,'Invalid unsigned PE checksum')
    offset,size=struct.unpack_from('<II',raw,security)
    require(offset%8==0 and unsigned_length<=offset<unsigned_length+8 and size>=8 and offset+size==len(raw),'Only an appended aligned certificate table is permitted')
    require(not any(raw[unsigned_length:offset]),'Nonzero added PE padding')
    length,revision,kind=struct.unpack_from('<IHH',raw,offset)
    require(revision==0x200 and kind==2 and 8<=length<=size and size-length<8 and not any(raw[offset+length:]),'One standard PKCS certificate table required')
    restored=bytearray(raw[:unsigned_length]);struct.pack_into('<I',restored,checksum,unsigned_pe_checksum);restored[security:security+8]=b'\0'*8
    require(hashlib.sha256(restored).hexdigest()==unsigned_sha256,'Signed bytes do not derive from the reproduced unsigned PE')
