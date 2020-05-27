"""
card: Library adapted to request (I)SIM cards and other types of telco cards.
Copyright (C) 2010 Benoit Michau

This program is free software; you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation; either version 2 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License along
with this program; if not, write to the Free Software Foundation, Inc.,
51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
"""


#################################
# Python library to work on
# ISIM card
# communication based on ISO7816 card
# and commands and formats based on UICC card
#
# needs pyscard from:
# http://pyscard.sourceforge.net/
#################################

from card.ICC import UICC, ISO7816
from card.FS import *
from card.utils import *

ISIM_AID = [0xA0, 0x00, 0x00, 0x00, 0x87, 0x10, 0x04]

class ISIM(UICC):
    '''
    defines attributes, methods and facilities for ETSI / 3GPP USIM card
    check ISIM specifications in 3GPP TS 31.103
    
    inherits (eventually overrides) methods and objects from UICC class
    use self.dbg = 1 or more to print live debugging information
    '''
    
    def __init__(self):
        '''
        initializes like an ISO7816-4 card with CLA=0x00
        and checks available AID (Application ID) read from EF_DIR
        
        initializes on the MF
        '''
        # initialize like a UICC
        ISO7816.__init__(self, CLA=0x00)
        self.AID = []
        if self.dbg:
            print '[DBG] type definition: %s' % type(self)
            print '[DBG] CLA definition: %s' % hex(self.CLA)
        
        # USIM selection from AID
        print '[+] UICC AID found:'
        self.get_AID()
        for aid in self.AID:
            if  tuple(aid[0:5]) == (0xA0, 0x00, 0x00, 0x00, 0x87) \
            and tuple(aid[5:7]) == (0x10, 0x04) :
                isim = self.select( Data=aid, typ='aid')
                if isim is None: 
                    print '[+] ISIM AID selection failed'
                else: 
                    print '[+] ISIM AID selection succeeded\n'
        
    def get_imsi(self):
        '''
        get_imsi() -> string(IMSI)
        
        reads IMSI value at address [0x6F, 0x07]
        returns IMSI string on success or None on error
        '''
        # select IMSI file
        self.select([0x3F, 0x00])
        self.select([0x7F, 0x20])
        imsi = self.select([0x6F, 0x07])
        self.select( Data=ISIM_AID, typ='aid')
        if imsi is None:
            return None
        # and parse the received data into the IMSI structure
        if 'Data' in imsi.keys() and len(imsi['Data']) == 9:
            return decode_BCD(imsi['Data'])[3:]
        
        # if issue with the content of the DF_IMSI file
        if self.dbg: 
            print '[DBG] %s' % self.coms()
        return None
    
    def get_GBA_BP(self):
        '''
        get_GBA_BP() -> [[RAND, B-TID, KeyLifetime], ...], 
        Length-Value parsing style
        
        reads EF_GBABP file at address [0x6F, 0xD5], 
            containing RAND and associated B-TID and KeyLifetime
        returns list of list of bytes on success 
            (or eventually the whole file dict if the format is strange)
        or None on error
        '''
        EF_GBABP = self.select( [0x6F, 0xD5] )
        if self.coms()[2] == (0x90, 0x00):
            if len(EF_GBABP['Data']) > 2:
                #RAND, B_TID, Lifetime = LV_parser( EF_GBABP['Data'] )
                print '[+] Successful GBA_BP selection: Get list of ' \
                      '[RAND, B-TID, KeyLifetime]'
                #return (RAND, B_TID, Lifetime)
                return LV_parser( EF_GBABP['Data'] )
            else: 
                return EF_GBABP
        return None
    
    def update_GBA_BP(self, RAND, B_TID, key_lifetime):
        '''
        update_GBA_BP([RAND], [B_TID], [key_lifetime]) 
            -> void (or EF_GBABP file dict if RAND not found)
        
        reads EF_GBABP file at address [0x6F, 0xD5],
        checks if RAND provided is referenced, 
        and updates the file structure with provided B-TID and KeyLifetime
        returns nothing (or eventually the whole file dict
        if the RAND is not found)
        '''
        GBA_BP = self.get_GBA_BP()
        for i in GBA_BP:
            if i == RAND:
                print '[+] RAND found in GBA_BP'
                # update transparent file with B_TID and key lifetime
                self.coms.push( self.UPDATE_BINARY( P2=len(RAND)+1,
                                Data=[len(B_TID)] + B_TID + \
                                [len(key_lifetime)] + key_lifetime ))
                if self.dbg > 1: 
                    print '[DBG] %s' % self.coms()
                if self.coms()[2] == 0x90 and self.dbg:
                    print '[+] Successful GBA_BP update with B-TID ' \
                          'and key lifetime'
                if self.dbg > 2: 
                    print '[DBG] new value of EF_GBA_BP:\n%s' \
                          % self.get_GBA_BP()
            else:
                if self.dbg: 
                    print '[+] RAND not found in GBA_BP'
                return GBA_BP
    
    def get_GBA_NL(self):
        '''
        get_GBA_NL() -> [[NAF_ID, B-TID], ...] , TLV parsing style
        
        reads EF_GBANL file at address [0x6F, 0xD7], containing NAF_ID and B-TID
        returns list of list of bytes vector on success 
            (or eventually the whole file dict if the format is strange)
        or None on error
        '''
        EF_GBANL = self.select( [0x6F, 0xD7] )
        if self.coms()[2] == (0x90, 0x00):
            if len(EF_GBANL['Data'][0]) > 2:
                # This is Tag-Length-Value parsing, 
                # with 0x80 for NAF_ID and 0x81 for B-TID
                values = []
                
                for rec in EF_GBANL['Data']:
                    NAF_ID, B_TID = [], []
                    while len(rec) > 0:
                        tlv = first_TLV_parser( rec )
                        if tlv[1] > 0xFF:
                            rec = rec[ tlv[1]+4 : ]
                        else:
                            rec = rec[ tlv[1]+2 : ]
                        if tlv[0] == 0x80: 
                            NAF_ID = tlv[2]
                        elif tlv[0] == 0x81: 
                            B_TID = tlv[2]
                    values.append( [NAF_ID, B_TID] )
                
                print '[+] Successful GBA_NL selection: ' \
                      'Get list of [NAF_ID, B-TID]'
                #return (NAF_ID, B_TID)
                return values
            else: 
                return EF_GBANL
        return None
    
    def authenticate(self, RAND=[], AUTN=[], ctx='3G'):
        '''
        self.authenticate(RAND, AUTN, ctx='3G') -> [key1, key2...], 
        LV parsing style
        
        runs the INTERNAL AUTHENTICATE command in the ISIM 
        with the right context:
            ctx = '2G', '3G', 'GBA' ('MBMS' or other not supported at this time)
            RAND and AUTN are list of bytes; for '2G' context, AUTN is not used
        returns a list containing the keys (list of bytes) computed in the ISIM,
        on success:
            [RES, CK, IK (, Kc)] or [AUTS] for '3G'
            [RES] or [AUTS] for 'GBA'
            [RES, Kc] for '2G'
        or None on error
        '''
        # prepare input data for authentication
        if ctx in ('3G', 'VGCS', 'GBA', 'MBMS') and len(RAND) != 16 \
        and len(AUTN) != 16: 
            print '[ERR] missing parameters or wrong length'
            return None
        
        inp = []
        if ctx == '3G':
            P2 = 0x81
        elif ctx == 'VGCS':
            P2 = 0x82
            print '[+] Not implemented. Exit.'
            return None
        elif ctx == 'MBMS':
            print '[+] Not implemented. Exit.'
            return None
        elif ctx == 'GBA': 
            P2 = 0x84
            inp = [0xDD]
        inp.extend( [len(RAND)] + RAND + [len(AUTN)] + AUTN )
        if ctx not in ['3G', 'VGCS', 'MBMS', 'GBA']: 
        # and also, if ctx == '2G'... the safe way 
        # to avoid desynchronizing our USIM counter
            P2 = 0x80
            if len(RAND) != 16: 
                print '[ERR] RAND has wrong length (%d, should be 16)' % len(RAND)
                return None
            # override input value for 2G authent
            inp = [len(RAND)] + RAND

        self.coms.push( self.INTERNAL_AUTHENTICATE(P2=P2, Data=inp) )
        if self.coms()[2][0] in (0x9F, 0x61):
            self.coms.push( self.GET_RESPONSE(Le=self.coms()[2][1]) )
            if self.coms()[2] == (0x90, 0x00):
                val = self.coms()[3]
                if P2 == 0x80:
                    if self.dbg: 
                        print '[+] Successful 2G authentication. Get [RES, Kc]'
                    values = LV_parser(val)
                    # returned values are (RES, Kc)
                    return values
                # not adapted to 2G context with Kc, RES: to be confirmed...
                if val[0] == 0xDB:
                    if self.dbg:
                        if P2 == 0x81:
                            print '[+] Successful 3G authentication. ' \
                                  'Get [RES, CK, IK(, Kc)]'
                        elif P2 == 0x84:
                            print '[+] Successful GBA authentication. Get [RES]'
                        else:
                            print '[+] response: %s' % hex(val)
                    values = LV_parser(val[1:])
                    # returned values can be (RES, CK, IK) or (RES, CK, IK, Kc)
                    return values
                elif val[0] == 0xDC:
                    if self.dbg: 
                        print '[+] Synchronization failure. Get [AUTS]'
                    values = LV_parser(val[1:])
                    return values
                elif self.dbg:
                    print '[+] response: %s' % hex(val)
        #else:
        if self.dbg: 
            print '[+] authentication error: %s' % self.coms()
        return None
    
    def GBA_derivation(self, NAF_ID=[], IMPI=[]):
        '''
        self.GBA_derivation(NAF_ID, IMPI) -> [Ks_ext_naf]
        
        runs the INTERNAL AUTHENTICATE command in the USIM 
        with the GBA derivation context:
            NAF_ID is a list of bytes (use stringToByte())
                "NAF domain name"||"security protocol id", 
                eg: "application.org"||"0x010001000a" (> TLS with RSA and SHA)
            IMPI is a list of bytes
                "IMSI@ims.mncXXX.mccYYY.3gppnetwork.org" if no IMS IMPI
                is specifically defined in the USIM 
        returns a list with GBA ext key (list of bytes) computed in the USIM:
            [Ks_ext_naf]
            Ks_int_naf remains available in the USIM 
            for further GBA_U key derivation
        or None on error
        
        see TS 33.220 for GBA specific formats
        '''
        # need to run 1st an authenicate command with 'GBA' context, 
        # so to have the required keys in the USIM
        P2 = 0x84
        inp = [0xDE] + [len(NAF_ID)] + NAF_ID + [len(IMPI)] + IMPI
        
        self.coms.push( self.INTERNAL_AUTHENTICATE(P2=P2, Data=inp) )
        if self.coms()[2][0] in (0x9F, 0x61):
            self.coms.push( self.GET_RESPONSE(Le=self.coms()[2][1]) )
            if self.coms()[2] == (0x90, 0x00):
                val = self.coms()[3]
                if val[0] == 0xDB: # not adapted to 2G context with Kc, RES
                    if self.dbg: 
                        print '[+] Successful GBA derivation. Get [Ks_EXT_NAF]'
                    values = LV_parser(val[1:])
                    return values
        if self.dbg: 
            print '[DBG] authentication failure: %s' % self.coms()
        return None

# vim: tabstop=4 shiftwidth=4 expandtab
