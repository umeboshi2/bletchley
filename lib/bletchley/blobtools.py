'''
A collection of tools to assist in analyzing encrypted blobs of data

Copyright (C) 2011-2013 Virtual Security Research, LLC
Author: Timothy D. Morgan, Jason A. Donenfeld

 This program is free software: you can redistribute it and/or modify
 it under the terms of the GNU Lesser General Public License, version 3,
 as published by the Free Software Foundation.

 This program is distributed in the hope that it will be useful,
 but WITHOUT ANY WARRANTY; without even the implied warranty of
 MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 GNU General Public License for more details.

 You should have received a copy of the GNU General Public License
 along with this program.  If not, see <http://www.gnu.org/licenses/>.
'''

import sys
import base64
import binascii
import traceback
import fractions
import operator
import functools
from . import buffertools


# urllib.parse's functions are not well suited for encoding/decoding
# bytes or managing encoded case 
def _percentEncode(binary, plus=False, upper=True):
    fmt = "%%%.2X"
    if upper:
        fmt = "%%%.2x"

    ret_val = bytearray(b'')
    for c in binary:
        if c not in b'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789':
            ret_val.extend((fmt % c).encode('ascii'))
        elif plus and (c == 20):
            ret_val.extend(b'+')
        else:
            ret_val.append(c)
    
    return ret_val


def _percentDecode(binary, plus=False):
    if plus:
        binary = binary.replace(b'+', b' ')
    if binary == b'':
        return b''
    chunks = binary.split(b'%')

    ret_val = chunks[0]
    for chunk in chunks[1:]:
        if len(chunk) < 2:
            return None
        try:
            ret_val += bytes([int(chunk[0:2], 16)]) + chunk[2:]
        except:
            #traceback.print_exc()
            #print(repr(chunk), repr(binary))
            return None
            
    return ret_val


# abstract class
class DataEncoding(object):
    charset = frozenset(b'')
    extraneous_chars = b''
    dialect = None
    name = None
    priority = None

    def __init__(self, dialect=''):
        self.dialect = dialect

    def isExample(self, blob):
        sblob = frozenset(blob)
        if self.charset != None and not sblob.issubset(self.charset):
            return False
        return self.extraTests(blob)
    
    def extraTests(self, blob):
        """May return True, False, or None, for is an example, isn't an
        example, or unknown, respectively. 

        """
        return True

    def decode(self, blob):
        return None

    def encode(self, blob):
        return None


class base64Encoding(DataEncoding):
    name = 'base64'
    def __init__(self, dialect='rfc3548'):
        super(base64Encoding, self).__init__(dialect)
        if dialect.startswith('rfc3548'):
            self.c62 = b'+'
            self.c63 = b'/'
            self.pad = b'='
        elif dialect.startswith('filename'):
            self.c62 = b'+'
            self.c63 = b'-'
            self.pad = b'='
        elif dialect.startswith('url1'):
            self.c62 = b'-'
            self.c63 = b'_'
            self.pad = b'='
        elif dialect.startswith('url2'):
            self.c62 = b'-'
            self.c63 = b'_'
            self.pad = b'.'
        elif dialect.startswith('url3'):
            self.c62 = b'_'
            self.c63 = b'-'
            self.pad = b'.'
        elif dialect.startswith('url4'):
            self.c62 = b'-'
            self.c63 = b'_'
            self.pad = b'!'
        elif dialect.startswith('url5'):
            self.c62 = b'+'
            self.c63 = b'/'
            self.pad = b'$'
        elif dialect.startswith('url6'):
            self.c62 = b'*'
            self.c63 = b'/'
            self.pad = b'='
        elif dialect.startswith('otkurl'):
            self.c62 = b'-'
            self.c63 = b'_'
            self.pad = b'*'
        elif dialect.startswith('xmlnmtoken'):
            self.c62 = b'.'
            self.c63 = b'-'
            self.pad = b'='
        elif dialect.startswith('xmlname'):
            self.c62 = b'_'
            self.c63 = b':'
            self.pad = b'='
        
        if 'newline' in dialect:
            self.extraneous_chars = b'\r\n'

        self.charset = frozenset(b'ABCDEFGHIJKLMNOPQRSTUVWXYZ'
                                 +b'abcdefghijklmnopqrstuvwxyz0123456789'
                                 +self.c62+self.c63+self.pad+self.extraneous_chars)

    def _guessPadLength(self, nopad_len):
        length = ((4 - nopad_len % 4) % 4)
        if length != 3:
            return length
        return None

    def extraTests(self, blob):
        for c in self.extraneous_chars:
            blob = blob.replace(bytes([c]), b'')

        if self.dialect.endswith('intpad'):
            if blob[-1] not in b'012':
                return False
            nopad = blob[:-1]
            padlen = blob[-1] - 48 # see the ascii table
        else:
            nopad = blob.rstrip(self.pad)
            padlen = len(blob) - len(nopad)

        # what the pad length ought to be
        padlen_guess = self._guessPadLength(len(nopad))
        if padlen_guess == None:
            return False

        # we don't accept bad pads, only missing pads
        if self.dialect.endswith('nopad'):
            return self.pad not in blob

        # pad must not appear in the middle of the 
        # string and must be the correct length at the end
        return (self.pad not in nopad) and (padlen == padlen_guess)

    def decode(self, blob):
        for c in self.extraneous_chars:
            blob = blob.replace(bytes(c), b'')

        if self.dialect.endswith('intpad'):
            padlen = blob[-1] - 48 # see the ascii table
            padlen_guess = self._guessPadLength(len(blob[:-1]))
            if padlen != padlen_guess:
                raise Exception("Invalid length for int-padded base64 string. (%d != %d)" 
                                % (padlen, padlen_guess))

            blob = blob[:-1] + (self.pad*padlen)

        if self.dialect.endswith('nopad'):
            if self.pad in blob:
                raise Exception("Unpadded base64 string contains pad character")

            padlen = self._guessPadLength(len(blob))
            if padlen == None:
                raise Exception("Invalid length for unpadded base64 string.")

            blob = blob+(self.pad*padlen)

        if not self.dialect.startswith('rfc3548'):
            table = bytes.maketrans(self.c62+self.c63+self.pad, b'+/=')
            blob = blob.translate(table)

        return base64.standard_b64decode(blob)


    def encode(self, blob):
        ret_val = base64.standard_b64encode(blob)

        if not self.dialect.startswith('rfc3548'):
            table = bytes.maketrans(b'+/=', self.c62+self.c63+self.pad)
            ret_val = ret_val.translate(table)

        if ret_val != None and self.dialect.endswith('nopad'):
            ret_val = ret_val.rstrip(self.pad)

        if ret_val != None and self.dialect.endswith('intpad'):
            stripped = ret_val.rstrip(self.pad) 
            ret_val = stripped + ("%d" % (len(ret_val) - len(stripped))).encode('utf-8')

        return ret_val


class base32Encoding(DataEncoding):
    name = 'base32'
    def __init__(self, dialect='rfc3548upper'):
        super(base32Encoding, self).__init__(dialect)
        if dialect.startswith('rfc3548upper'):
            self.pad = b'='
            self.charset = frozenset(b'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567'+self.pad)

        elif dialect.startswith('rfc3548lower'):
            self.pad = b'='
            self.charset = frozenset(b'abcdefghijklmnopqrstuvwxyz234567'+self.pad)

    def _guessPadLength(self, nopad_len):
        pad_lengths = {0:0, 7:1, 5:3, 4:4, 2:6}
        return pad_lengths.get(nopad_len%8, None)  

    def extraTests(self, blob):
        nopad = blob.rstrip(self.pad)
        padlen_guess = self._guessPadLength(len(nopad))
        if padlen_guess == None:
            return False

        # we don't accept bad pads, only missing pads
        if self.dialect.endswith('nopad'):
            return self.pad not in blob

        # pad must not appear in the middle of the 
        # string and must be the correct length at the end
        return (self.pad not in nopad) and (len(blob) == len(nopad)+padlen_guess)


    def decode(self, blob):
        if self.dialect.endswith('nopad'):
            if self.pad in blob:
                raise Exception("Unpadded base32 string contains pad character")

            padlen = self._guessPadLength(len(blob))
            if padlen == None:
                raise Exception("Invalid length for unpadded base64 string.")

            blob = blob+(self.pad*padlen)

        return base64.b32decode(blob.upper())


    def encode(self, blob):
        ret_val = base64.b32encode(blob)

        if ret_val != None and self.dialect.endswith('nopad'):
            ret_val = ret_val.rstrip(self.pad)

        if 'lower' in self.dialect:
            ret_val = ret_val.lower()
        else:
            ret_val = ret_val.upper()

        return ret_val


class hexEncoding(DataEncoding):
    name = 'hex'
    def __init__(self, dialect='mixed'):
        super(hexEncoding, self).__init__(dialect)
        if 'mixed' in dialect:
            self.charset = frozenset(b'ABCDEFabcdef0123456789')
        elif 'upper' in dialect:
            self.charset = frozenset(b'ABCDEF0123456789')            
        elif 'lower' in dialect:
            self.charset = frozenset(b'abcdef0123456789')


    def extraTests(self, blob):
        return (len(blob) % 2 == 0)

    def decode(self, blob):
        return binascii.a2b_hex(blob)

    def encode(self, blob):
        if 'upper' in self.dialect:
            return binascii.b2a_hex(blob).upper()
        if 'lower' in self.dialect:
            return binascii.b2a_hex(blob).lower()
        else:
            return binascii.b2a_hex(blob)


class percentEncoding(DataEncoding):
    name = 'percent'
    def __init__(self, dialect='mixed'):
        super(percentEncoding, self).__init__(dialect)
        self.charset = None
        if 'mixed' in dialect:
            self.hexchars = frozenset(b'ABCDEFabcdef0123456789')
        elif 'upper' in dialect:
            self.hexchars = frozenset(b'ABCDEF0123456789')            
        elif 'lower' in dialect:
            self.hexchars = frozenset(b'abcdef0123456789')

    def extraTests(self, blob):
        chunks = blob.split(b'%')
        if len(chunks) < 2:
            return None
        for c in chunks[1:]:
            if len(c) < 2:
                return False
            if (c[0] not in self.hexchars) or (c[1] not in self.hexchars):
                return False
        return True

    def decode(self, blob):
        plus = False
        if 'plus' in self.dialect:
            plus = True
        return _percentDecode(blob, plus=plus)

    def encode(self, blob):
        upper = True
        plus = False
        if 'plus' in self.dialect:
            plus = True
        if 'lower' in self.dialect:
            upper = False

        return _percentEncode(blob, plus=plus, upper=upper)

# XXX: need a better way to organize these with the possible combinations of dialects, padding, etc
#      for instance, can we have rfc3548-newline-nopad ?
priorities = [
    (hexEncoding, 'upper', 100),
    (hexEncoding, 'lower', 101),
    (hexEncoding, 'mixed', 102),
    (base32Encoding, 'rfc3548upper', 150),
    (base32Encoding, 'rfc3548lower', 151),
    (base32Encoding, 'rfc3548upper-nopad', 160),
    (base32Encoding, 'rfc3548lower-nopad', 161),
    (base64Encoding, 'rfc3548', 200),
    (base64Encoding, 'rfc3548-nopad', 201),
    (base64Encoding, 'rfc3548-newline', 202),
    (base64Encoding, 'rfc3548-intpad', 203),
    (base64Encoding, 'filename', 210),
    (base64Encoding, 'filename-nopad', 211),
    (base64Encoding, 'filename-intpad', 212),
    (base64Encoding, 'url1', 230),
    (base64Encoding, 'url1-nopad', 231),
    (base64Encoding, 'url1-intpad', 232),
    (base64Encoding, 'otkurl', 235),
    (base64Encoding, 'otkurl-nopad', 236),
    (base64Encoding, 'otkurl-intpad', 237),
    (base64Encoding, 'url2', 240),
    (base64Encoding, 'url2-nopad', 241),
    (base64Encoding, 'url2-intpad', 242),
    (base64Encoding, 'url3', 250),
    (base64Encoding, 'url3-nopad', 251),
    (base64Encoding, 'url3-intpad', 252),
    (base64Encoding, 'url4', 260),
    (base64Encoding, 'url4-nopad', 261),
    (base64Encoding, 'url4-intpad', 262),
    (base64Encoding, 'url5', 265),
    (base64Encoding, 'url5-nopad', 266),
    (base64Encoding, 'url5-intpad', 267),
    (base64Encoding, 'url6', 267),
    (base64Encoding, 'url6-nopad', 268),
    (base64Encoding, 'url6-intpad', 269),
    (base64Encoding, 'xmlnmtoken', 270),
    (base64Encoding, 'xmlnmtoken-nopad', 271),
    (base64Encoding, 'xmlnmtoken-intpad', 272),
    (base64Encoding, 'xmlname', 280),
    (base64Encoding, 'xmlname-nopad', 281),
    (base64Encoding, 'xmlname-intpad', 282),
    (percentEncoding, 'upper-plus', 400),
    (percentEncoding, 'upper', 401),
    (percentEncoding, 'lower-plus', 410),
    (percentEncoding, 'lower', 411),
    (percentEncoding, 'mixed-plus', 420),
    (percentEncoding, 'mixed', 421),
    ]

encodings = {}
for enc,d,p in priorities:
    e = enc(d)
    e.priority = p
    encodings["%s/%s" % (enc.name, d)] = e


def supportedEncodings():
    e = list(encodings.keys())
    e.sort()
    return e


def possibleEncodings(blob):
    likely = set()
    possible = set()
    for name,encoding in encodings.items():
        result = encoding.isExample(blob)
        if result == True:
            likely.add(name)
        elif result == None:
            possible.add(name)
    return likely,possible


def encodingIntersection(blobs):
    ret_val = set(encodings.keys())
    p = set(encodings.keys())
    for b in blobs:
        likely,possible = possibleEncodings(b)
        ret_val &= likely | possible
        p &= possible
    return ret_val - p


def bestEncoding(encs):
    priority = 999999999
    best = None
    for e in encs:
        if encodings[e].priority < priority:
            best = e
            priority = encodings[e].priority
    return best


def decode(encoding, blob):
    """Given an encoding name and a blob, decodes the blob and returns it.

    encoding -- A string representation of the encoding and dialect.
                For a list of valid encoding names, run: 
                  bletchley-analyze -e ?

    blob     -- A bytes or bytearray object to be decoded.  If a string
                is provided instead, it will be converted to a bytes
                object using 'utf-8'.

    Returns a bytes object containing the decoded representation of
    blob.  Will throw various types of exceptions if a problem is
    encountered.
    """
    if isinstance(blob, str):
        blob = blob.encode('utf-8')
    return encodings[encoding].decode(blob)

def encode(encoding, blob):
    """Given an encoding name and a blob, encodes the blob and returns it.

    encoding -- A string representation of the encoding and dialect.
                For a list of valid encoding names, run: 
                  bletchley-analyze -e ?

    blob     -- A bytes or bytearray object to be encoded.

    Returns a bytes object containing the encoded representation of
    blob.  Will throw various types of exceptions if a problem is
    encountered."""
    return encodings[encoding].encode(blob)


def decodeAll(encoding, blobs):
    return [encodings[encoding].decode(b) for b in blobs]


def encodeAll(encoding, blobs):
    return [encodings[encoding].encode(b) for b in blobs]


def decodeChain(decoding_chain, blob):
    """Given a sequence of encoding names (decoding_chain) and a blob,
    decodes the blob once for each element of the decoding_chain. For
    instance, if the decoding_chain were 
      ['percent/lower', 'base64/rfc3548']
    then blob would first be decoded as 'percent/lower', followed by
    'base64/rfc3548'.

    decoding_chain -- A sequence (list,tuple,...) of string
                      representations of the encoding and dialect. For a
                      list of valid encoding names, run:  
                         bletchley-analyze -e ?

    blob     -- A bytes or bytearray object to be decoded.  If a string
                is provided instead, it will be converted to a bytes
                object using 'utf-8'.

    Returns a bytes object containing the decoded representation of
    blob.  Will throw various types of exceptions if a problem is
    encountered.
    """
    for decoding in decoding_chain:
        blob = decode(decoding, blob)
    return blob


def encodeChain(encoding_chain, blob):
    """Given a sequence of encoding names (encoding_chain) and a blob,
    encodes the blob once for each element of the encoding_chain. For
    instance, if the encoding_chain were 
      ['base64/rfc3548', 'percent/lower',]
    then blob would first be encoded as 'base64/rfc3548', followed by
    'percent/lower'.

    encoding_chain -- A sequence (list,tuple,...) of string
                      representations of the encoding and dialect. For a
                      list of valid encoding names, run:  
                         bletchley-analyze -e ?

    blob     -- A bytes or bytearray object to be encoded.

    Returns a bytes object containing the encoded representation of
    blob.  Will throw various types of exceptions if a problem is
    encountered.
    """    
    for encoding in encoding_chain:
        blob = encode(encoding, blob)
    return blob


def getLengths(s):
    lengths = set()
    for bin in s:
        lengths.add(len(bin))
    lengths = list(lengths)
    lengths.sort()
    return lengths


def maxBlockSize(blob_lengths):
    divisor = 0
    for bl in blob_lengths:
        divisor = fractions.gcd(divisor, bl)

    return divisor


allTrue = functools.partial(functools.reduce, (lambda x,y: x and y))

def checkCommonBlocksizes(lengths):
    common_block_sizes = (8,16,20)
    ret_val = []
    for cbs in common_block_sizes:
        gcdIsCBS = (lambda x: fractions.gcd(x,cbs)==cbs)
        if allTrue(map(gcdIsCBS, lengths)):
            ret_val.append(cbs)
    return ret_val


def int2binary(x, bits=8):
        """
        Integer to binary
        Count is number of bits
        """
        return "".join(map(lambda y:str((x>>y)&1), range(bits-1, -1, -1)))
