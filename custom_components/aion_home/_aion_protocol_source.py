from __future__ import annotations
from typing import Any
import base64
import hashlib
import hmac
import json
import secrets
import time
from urllib.parse import quote
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad
from .const import LOCAL_AC_ACTION, LOCAL_AUX_COMMANDS, LOCAL_COMMAND, LOCAL_INIT, LOCAL_IR_ACTION, LOCAL_RESTART_COMMAND, LOCAL_STATE
_DEFAULT_PROTOCOL_SOURCE = 'homeassistant'
_DEFAULT_PROTOCOL_USER = 'admin'
OOOOO00000O0 = frozenset({'devDecError', 'appDecryptionErr'})

class AionProtocolError(Exception):
    pass

class AionProtocolCore:

    def build_init_request(OOO0OO000O0O, OO0O00OO0000: dict[str, Any]) -> dict[str, Any]:
        OOOOO00000OO = str(OO0O00OO0000.get('main_key', ''))
        if len(OOOOO00000OO) != 128:
            raise AionProtocolError('Device main key is missing or malformed.')
        OO000OOOOOO0 = OOOOO00000OO[:64]
        OO00OOO0000O = OOOOO00000OO[64:128]
        O0OO0OO0OO00 = OOOOO00000OO[32:96]
        OO00OO0OOOOO = OOO0OO000O0O._timestamp_ms()
        OOOOOOOOO0O0 = secrets.token_hex(32)
        return {'endpoint': LOCAL_INIT, 'plaintext': f"{OO0O00OO0000['ssid_suffix']},{OO00OO0OOOOO},{OOOOOOOOO0O0}", 'encryption_key': OO000OOOOOO0, 'decryption_key': OO00OOO0000O, 'created_at_ms': OO00OO0OOOOO, 'rand_data': OOOOOOOOO0O0, 'mac_key': O0OO0OO0OO00}

    def finalize_session(OO0O0OOOOO0O, O00000O0O000: str, OO00O0OOO0OO: dict[str, Any]) -> dict[str, Any]:
        try:
            O00OOOOO0OO0 = json.loads(O00000O0O000)
        except json.JSONDecodeError as error:
            raise AionProtocolError('Device init response is not valid JSON.') from error
        if not isinstance(O00OOOOO0OO0, dict):
            raise AionProtocolError('Device init response is not valid JSON.')
        O000O00OO00O = str(OO00O0OOO0OO['rand_data'])
        if O00OOOOO0OO0.get('r') != O000O00OO00O:
            raise AionProtocolError('Device init challenge verification failed.')
        try:
            O0OO0OO00O00 = hmac.new(bytes.fromhex(str(OO00O0OOO0OO['mac_key'])), O000O00OO00O.encode('utf-8'), hashlib.sha256).hexdigest()
        except ValueError as error:
            raise AionProtocolError('Device main key is missing or malformed.') from error
        return {'z_key': O0OO0OO00O00, 'created_at_ms': int(OO00O0OOO0OO['created_at_ms']), 'json_mode': O00OOOOO0OO0.get('com') == 'json'}

    def is_session_fresh(OOOO000O0OOO, O0O00OOO00O0: dict[str, Any] | None, OOO000OO0O0O: int) -> bool:
        if not O0O00OOO00O0:
            return False
        try:
            OO0O00O00000 = int(O0O00OOO00O0.get('created_at_ms', 0))
        except (TypeError, ValueError):
            return False
        return OOOO000O0OOO._timestamp_ms() - OO0O00O00000 <= OOO000OO0O0O

    def build_operation_request(O0OOOOOO00OO, O00O0OO0OOO0: str, OOO00O0O000O: dict[str, Any], OO0O0O0OOO00: dict[str, Any], O0OO0O00OOOO: dict[str, Any], command_payload: Any=None) -> dict[str, Any]:
        OOO0OOO0O0O0 = str(O0OO0O00OOOO.get('z_key', ''))
        if not OOO0OOO0O0O0:
            raise AionProtocolError('A valid LAN session is required before sending device commands.')
        O000OOO0OO0O = O00O0OO0OOO0.strip().lower()
        if O000OOO0OO0O == 'primary':
            OO00000OO000 = O0OOOOOO00OO._build_primary_payload(OOO00O0O000O, OO0O0O0OOO00, O0OO0O00OOOO, command_payload)
            return {'endpoint': LOCAL_COMMAND, 'plaintext': OO00000OO000, 'encryption_key': OOO0OOO0O0O0, 'decryption_key': OOO0OOO0O0O0}
        if O000OOO0OO0O == 'aux':
            OO0O00O0O0OO = O0OOOOOO00OO._normalize_dict_payload(command_payload, 'aux')
            OO00000OO000 = O0OOOOOO00OO._build_json_payload(OO0O0O0OOO00['ssid_suffix'], O0OOOOOO00OO._with_action_metadata(OO0O00O0O0OO))
            return {'endpoint': LOCAL_AUX_COMMANDS, 'plaintext': OO00000OO000, 'encryption_key': OOO0OOO0O0O0, 'decryption_key': OOO0OOO0O0O0, 'normalized_payload': OO0O00O0O0OO}
        if O000OOO0OO0O == 'ir':
            O0O0OOO00OO0 = O0OOOOOO00OO._resolve_ir_command(OOO00O0O000O, command_payload)
            OOO00000O00O = O0OOOOOO00OO._timestamp_ms()
            OO00000OO000 = f"{OO0O0O0OOO00['ssid_suffix']},{OOO00000O00O},{O0O0OOO00OO0['protocol']},{O0O0OOO00OO0['code']},{O0O0OOO00OO0['size']}"
            return {'endpoint': LOCAL_IR_ACTION, 'plaintext': OO00000OO000, 'encryption_key': OOO0OOO0O0O0, 'decryption_key': OOO0OOO0O0O0}
        if O000OOO0OO0O == 'ac':
            OO0O00O0O0OO = O0OOOOOO00OO._normalize_dict_payload(command_payload, 'ac')
            O00O0O0O0O00 = OOO00O0O000O.get('state', {}).get('ac_state', {})
            O00OO0000OOO = O0OOOOOO00OO._merge_dict(O00O0O0O0O00, OO0O00O0O0OO)
            OO00000OO000 = O0OOOOOO00OO._build_json_payload(OO0O0O0OOO00['ssid_suffix'], O00OO0000OOO)
            return {'endpoint': LOCAL_AC_ACTION, 'plaintext': OO00000OO000, 'encryption_key': OOO0OOO0O0O0, 'decryption_key': OOO0OOO0O0O0, 'merged_ac_state': O00OO0000OOO}
        if O000OOO0OO0O == 'restart':
            return {'endpoint': LOCAL_RESTART_COMMAND, 'plaintext': f"{OO0O0O0OOO00['ssid_suffix']},{O0OOOOOO00OO._timestamp_ms()}", 'encryption_key': OOO0OOO0O0O0, 'decryption_key': OOO0OOO0O0O0}
        if O000OOO0OO0O == 'state':
            return {'endpoint': LOCAL_STATE, 'plaintext': f"{OO0O0O0OOO00['ssid_suffix']},{O0OOOOOO00OO._timestamp_ms()}", 'encryption_key': OOO0OOO0O0O0, 'decryption_key': OOO0OOO0O0O0}
        raise AionProtocolError(f'Unsupported command type: {O00O0OO0OOO0}')

    def build_encrypted_request(OO0O0OO000O0, OO0OO0O00O0O: str, OO0O000O0000: str) -> dict[str, str]:
        O0000OO000OO, OOO00O0OOOO0 = OO0O0OO000O0._encrypt(OO0OO0O00O0O, OO0O000O0000)
        return {'encoded_cipher': quote(O0000OO000OO, safe=''), 'iv_hex': OOO00O0OOOO0}

    def parse_encrypted_response(OOOOOO00000O, OOOO0O00OO00: str, O00OO0OOOOOO: str) -> str:
        OO0OOO0OO0O0 = OOOO0O00OO00.strip()
        if OO0OOO0OO0O0 == '':
            return ''
        if OO0OOO0OO0O0 in OOOOO00000O0:
            raise AionProtocolError('Device session is invalid and must be re-initialized.')
        try:
            OO000O0OOO0O = json.loads(OOOO0O00OO00)
        except json.JSONDecodeError:
            return OOOO0O00OO00
        if not isinstance(OO000O0OOO0O, dict):
            return OOOO0O00OO00
        O0000000O000 = OO000O0OOO0O.get('d')
        OO0OO00OO0OO = OO000O0OOO0O.get('v')
        if not isinstance(O0000000O000, str) or not isinstance(OO0OO00OO0OO, str):
            return OOOO0O00OO00
        O0OOOO0O0OO0 = OOOOOO00000O._decrypt(O0000000O000, OO0OO00OO0OO, O00OO0OOOOOO)
        O0OO0OOOO00O = O0OOOO0O0OO0.strip()
        if O0OO0OOOO00O in OOOOO00000O0:
            raise AionProtocolError('Device session is invalid and must be re-initialized.')
        return O0OOOO0O0OO0

    def parse_local_state_response(OOOO0O000O00, O0OOOOOO0OOO: str) -> Any:
        if O0OOOOOO0OOO.strip() == '':
            return None
        try:
            O0000O0O00O0 = json.loads(O0OOOOOO0OOO)
        except json.JSONDecodeError:
            return O0OOOOOO0OOO
        if isinstance(O0000O0O00O0, dict) and 'res' in O0000O0O00O0:
            return O0000O0O00O0['res']
        return O0000O0O00O0

    def _build_primary_payload(OO0O000O0O0O, OO0O00000000: dict[str, Any], OO00OO0O00OO: dict[str, Any], O0OO0O00OOO0: dict[str, Any], O00O00OO000O: Any) -> str:
        O00O00OOOO00 = OO0O00000000.get('control', {})
        O00000O0OOOO = OO0O000O0O0O._timestamp_ms()
        OO00OO00O0O0 = OO0O000O0O0O._action_id()
        OOOOOO00OO0O = O00O00OOOO00.get('gang_id')
        O0OOOOOOO000 = 200 if O00O00OO000O == 'stop' else O00O00OO000O
        if bool(O0OO0O00OOO0.get('json_mode')):
            OOO00000O0OO: dict[str, Any] = {'w': O0OOOOOOO000, 'src': _DEFAULT_PROTOCOL_SOURCE, 'usr': _DEFAULT_PROTOCOL_USER, 'actID': OO00OO00O0O0}
            if OOOOOO00OO0O:
                OOO00000O0OO['id'] = OOOOOO00OO0O
            OO00OO000OO0 = json.dumps(OOO00000O0OO, separators=(',', ':'))
        elif OOOOOO00OO0O:
            OO00OO000OO0 = f'{OOOOOO00OO0O}-{O0OOOOOOO000}'
        else:
            OO00OO000OO0 = str(O0OOOOOOO000)
        return f"{OO00OO0O00OO['ssid_suffix']},{O00000O0OOOO},{OO00OO000OO0}"

    def _resolve_ir_command(O000OOO0O00O, OO0O00OO0O00: dict[str, Any], OOO00OO00OOO: Any) -> dict[str, str]:
        if isinstance(OOO00OO00OOO, str):
            O0OO0O0000O0 = OO0O00OO0O00.get('control', {})
            OO00O0000O0O = O0OO0O0000O0.get('commands', {})
            OO00OOOO0000 = OO00O0000O0O.get(OOO00OO00OOO)
            if isinstance(OO00OOOO0000, dict):
                return {'protocol': str(OO00OOOO0000['protocol']), 'size': str(OO00OOOO0000['size']), 'code': str(OO00OOOO0000['code'])}
            if OO00OOOO0000 is None:
                raise AionProtocolError(f"IR command '{OOO00OO00OOO}' does not exist.")
            O00O0O0000OO = O0OO0O0000O0.get('protocol')
            O00000OOOOO0 = O0OO0O0000O0.get('size')
            if O00O0O0000OO is None or O00000OOOOO0 is None:
                raise AionProtocolError('IR command metadata is missing protocol or size information.')
            return {'protocol': str(O00O0O0000OO), 'size': str(O00000OOOOO0), 'code': str(OO00OOOO0000)}
        O0O0O0O0000O = O000OOO0O00O._normalize_dict_payload(OOO00OO00OOO, 'ir')
        O0OO00O0OO00 = {'protocol', 'size', 'code'}
        if not O0OO00O0OO00.issubset(O0O0O0O0000O.keys()):
            raise AionProtocolError('IR payload must contain protocol, size, and code.')
        return {'protocol': str(O0O0O0O0000O['protocol']), 'size': str(O0O0O0O0000O['size']), 'code': str(O0O0O0O0000O['code'])}

    def _normalize_dict_payload(OOO0O00OOOOO, O0OOO0OOO0O0: Any, O0OO00OOOO0O: str) -> dict[str, Any]:
        if not isinstance(O0OOO0OOO0O0, dict):
            raise AionProtocolError(f'{O0OO00OOOO0O} payload must be a JSON object.')
        return O0OOO0OOO0O0

    def _with_action_metadata(OOOOOOO0O000, OOO00OOOO0OO: dict[str, Any]) -> dict[str, Any]:
        OO0OO0OO0OO0 = dict(OOO00OOOO0OO)
        OO0OO0OO0OO0.setdefault('actID', OOOOOOO0O000._action_id())
        OO0OO0OO0OO0.setdefault('src', _DEFAULT_PROTOCOL_SOURCE)
        OO0OO0OO0OO0.setdefault('usr', _DEFAULT_PROTOCOL_USER)
        return OO0OO0OO0OO0

    def _build_json_payload(OOO00O0OO00O, O0OO00O00O00: str, O000OO0O0OOO: dict[str, Any]) -> str:
        return f"{O0OO00O00O00},{OOO00O0OO00O._timestamp_ms()},{json.dumps(O000OO0O0OOO, separators=(',', ':'))}"

    def _merge_dict(OOO000OO00O0, O0OOOOOO0O0O: dict[str, Any], OO00OOO00000: dict[str, Any]) -> dict[str, Any]:
        OO0OO0OO00OO = dict(O0OOOOOO0O0O)
        for OO0O00O0OOO0, OO00000O000O in OO00OOO00000.items():
            if isinstance(OO00000O000O, dict) and isinstance(OO0OO0OO00OO.get(OO0O00O0OOO0), dict):
                OO0OO0OO00OO[OO0O00O0OOO0] = OOO000OO00O0._merge_dict(OO0OO0OO00OO[OO0O00O0OOO0], OO00000O000O)
            else:
                OO0OO0OO00OO[OO0O00O0OOO0] = OO00000O000O
        return OO0OO0OO00OO

    def _encrypt(OO0O000OOO00, OO0O0000OOOO: str, O0O0O0O0O0O0: str) -> tuple[str, str]:
        try:
            OOO0O0O0OO0O = secrets.token_bytes(16)
            O0OOOO0OO000 = AES.new(bytes.fromhex(O0O0O0O0O0O0), AES.MODE_CBC, OOO0O0O0OO0O)
            OOO0OOO0O0OO = O0OOOO0OO000.encrypt(pad(OO0O0000OOOO.encode('utf-8'), AES.block_size))
        except ValueError as error:
            raise AionProtocolError('Device encryption key is invalid.') from error
        return (base64.b64encode(OOO0OOO0O0OO).decode('ascii'), OOO0O0O0OO0O.hex())

    def _decrypt(OOO0O0O00OO0, O0OOOO00O00O: str, O00O000O0O00: str, O0OO0O000OOO: str) -> str:
        try:
            O00O00O000O0 = AES.new(bytes.fromhex(O0OO0O000OOO), AES.MODE_CBC, bytes.fromhex(O00O000O0O00))
            O0OO0OO00O0O = O00O00O000O0.decrypt(base64.b64decode(O0OOOO00O00O))
            return unpad(O0OO0OO00O0O, AES.block_size).decode('utf-8')
        except (ValueError, TypeError) as error:
            raise AionProtocolError('Encrypted device response could not be decrypted.') from error

    def _timestamp_ms(OO00OO0O0000) -> int:
        return int(time.time() * 1000)

    def _action_id(O0O000O000OO) -> str:
        return secrets.token_hex(3)