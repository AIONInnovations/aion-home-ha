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
O0OOO0O00000 = frozenset({'devDecError', 'appDecryptionErr'})

class AionProtocolError(Exception):
    pass

class AionProtocolCore:

    def build_init_request(O00O000O0O0O, O00OO0OOOOO0: dict[str, Any]) -> dict[str, Any]:
        O0OOOOO0O0OO = str(O00OO0OOOOO0.get('main_key', ''))
        if len(O0OOOOO0O0OO) != 128:
            raise AionProtocolError('Device main key is missing or malformed.')
        OO0O00O0OO00 = O0OOOOO0O0OO[:64]
        OOOO0O0O000O = O0OOOOO0O0OO[64:128]
        O00O0OO0O0O0 = O0OOOOO0O0OO[32:96]
        OO00OO000OOO = O00O000O0O0O._timestamp_ms()
        OO0OOOOOO000 = secrets.token_hex(32)
        return {'endpoint': LOCAL_INIT, 'plaintext': f"{O00OO0OOOOO0['ssid_suffix']},{OO00OO000OOO},{OO0OOOOOO000}", 'encryption_key': OO0O00O0OO00, 'decryption_key': OOOO0O0O000O, 'created_at_ms': OO00OO000OOO, 'rand_data': OO0OOOOOO000, 'mac_key': O00O0OO0O0O0}

    def finalize_session(O00OOO00OO0O, OOO00O0O0OO0: str, OOOOOOO000OO: dict[str, Any]) -> dict[str, Any]:
        try:
            O0O000000O00 = json.loads(OOO00O0O0OO0)
        except json.JSONDecodeError as error:
            raise AionProtocolError('Device init response is not valid JSON.') from error
        if not isinstance(O0O000000O00, dict):
            raise AionProtocolError('Device init response is not valid JSON.')
        OO00O000O00O = str(OOOOOOO000OO['rand_data'])
        if O0O000000O00.get('r') != OO00O000O00O:
            raise AionProtocolError('Device init challenge verification failed.')
        try:
            OO00O00000O0 = hmac.new(bytes.fromhex(str(OOOOOOO000OO['mac_key'])), OO00O000O00O.encode('utf-8'), hashlib.sha256).hexdigest()
        except ValueError as error:
            raise AionProtocolError('Device main key is missing or malformed.') from error
        return {'z_key': OO00O00000O0, 'created_at_ms': int(OOOOOOO000OO['created_at_ms']), 'json_mode': O0O000000O00.get('com') == 'json'}

    def is_session_fresh(O00O00OOOOOO, OO0O0O0O0000: dict[str, Any] | None, O0OOO0000O0O: int) -> bool:
        if not OO0O0O0O0000:
            return False
        try:
            OOOOOOO0OOO0 = int(OO0O0O0O0000.get('created_at_ms', 0))
        except (TypeError, ValueError):
            return False
        return O00O00OOOOOO._timestamp_ms() - OOOOOOO0OOO0 <= O0OOO0000O0O

    def build_operation_request(OO00OO0OO0OO, O0OOOO0OOO00: str, O0O0OO00000O: dict[str, Any], OO00O00OO0O0: dict[str, Any], OOO0O0OO0OOO: dict[str, Any], command_payload: Any=None) -> dict[str, Any]:
        O00OO0O0O000 = str(OOO0O0OO0OOO.get('z_key', ''))
        if not O00OO0O0O000:
            raise AionProtocolError('A valid LAN session is required before sending device commands.')
        OOO000OOOO0O = O0OOOO0OOO00.strip().lower()
        if OOO000OOOO0O == 'primary':
            OOO0O0000OO0 = OO00OO0OO0OO._build_primary_payload(O0O0OO00000O, OO00O00OO0O0, OOO0O0OO0OOO, command_payload)
            return {'endpoint': LOCAL_COMMAND, 'plaintext': OOO0O0000OO0, 'encryption_key': O00OO0O0O000, 'decryption_key': O00OO0O0O000}
        if OOO000OOOO0O == 'aux':
            O0O0OO0O00OO = OO00OO0OO0OO._normalize_dict_payload(command_payload, 'aux')
            OOO0O0000OO0 = OO00OO0OO0OO._build_json_payload(OO00O00OO0O0['ssid_suffix'], OO00OO0OO0OO._with_action_metadata(O0O0OO0O00OO))
            return {'endpoint': LOCAL_AUX_COMMANDS, 'plaintext': OOO0O0000OO0, 'encryption_key': O00OO0O0O000, 'decryption_key': O00OO0O0O000, 'normalized_payload': O0O0OO0O00OO}
        if OOO000OOOO0O == 'ir':
            O0O0O0OO0O00 = OO00OO0OO0OO._resolve_ir_command(O0O0OO00000O, command_payload)
            O00OOOOOO00O = OO00OO0OO0OO._timestamp_ms()
            OOO0O0000OO0 = f"{OO00O00OO0O0['ssid_suffix']},{O00OOOOOO00O},{O0O0O0OO0O00['protocol']},{O0O0O0OO0O00['code']},{O0O0O0OO0O00['size']}"
            return {'endpoint': LOCAL_IR_ACTION, 'plaintext': OOO0O0000OO0, 'encryption_key': O00OO0O0O000, 'decryption_key': O00OO0O0O000}
        if OOO000OOOO0O == 'ac':
            O0O0OO0O00OO = OO00OO0OO0OO._normalize_dict_payload(command_payload, 'ac')
            O00OO0OO00O0 = O0O0OO00000O.get('state', {}).get('ac_state', {})
            OO0O00O0OOOO = OO00OO0OO0OO._merge_dict(O00OO0OO00O0, O0O0OO0O00OO)
            OOO0O0000OO0 = OO00OO0OO0OO._build_json_payload(OO00O00OO0O0['ssid_suffix'], OO0O00O0OOOO)
            return {'endpoint': LOCAL_AC_ACTION, 'plaintext': OOO0O0000OO0, 'encryption_key': O00OO0O0O000, 'decryption_key': O00OO0O0O000, 'merged_ac_state': OO0O00O0OOOO}
        if OOO000OOOO0O == 'restart':
            return {'endpoint': LOCAL_RESTART_COMMAND, 'plaintext': f"{OO00O00OO0O0['ssid_suffix']},{OO00OO0OO0OO._timestamp_ms()}", 'encryption_key': O00OO0O0O000, 'decryption_key': O00OO0O0O000}
        if OOO000OOOO0O == 'state':
            return {'endpoint': LOCAL_STATE, 'plaintext': f"{OO00O00OO0O0['ssid_suffix']},{OO00OO0OO0OO._timestamp_ms()}", 'encryption_key': O00OO0O0O000, 'decryption_key': O00OO0O0O000}
        raise AionProtocolError(f'Unsupported command type: {O0OOOO0OOO00}')

    def build_encrypted_request(O0OO00000000, O00OOOOO0O0O: str, O0O0000OOOO0: str) -> dict[str, str]:
        O00OOO00O0OO, OOO0O000OO00 = O0OO00000000._encrypt(O00OOOOO0O0O, O0O0000OOOO0)
        return {'encoded_cipher': quote(O00OOO00O0OO, safe=''), 'iv_hex': OOO0O000OO00}

    def parse_encrypted_response(O0O000OO000O, O0OOOO00O0O0: str, OO00O0O00OOO: str) -> str:
        O00O0O0OO000 = O0OOOO00O0O0.strip()
        if O00O0O0OO000 == '':
            return ''
        if O00O0O0OO000 in O0OOO0O00000:
            raise AionProtocolError('Device session is invalid and must be re-initialized.')
        try:
            OOO0O0O0OO0O = json.loads(O0OOOO00O0O0)
        except json.JSONDecodeError:
            return O0OOOO00O0O0
        if not isinstance(OOO0O0O0OO0O, dict):
            return O0OOOO00O0O0
        O0O0O0OO0OO0 = OOO0O0O0OO0O.get('d')
        O00OOO0000OO = OOO0O0O0OO0O.get('v')
        if not isinstance(O0O0O0OO0OO0, str) or not isinstance(O00OOO0000OO, str):
            return O0OOOO00O0O0
        OOOO0OO00O00 = O0O000OO000O._decrypt(O0O0O0OO0OO0, O00OOO0000OO, OO00O0O00OOO)
        O0OO0OO0O00O = OOOO0OO00O00.strip()
        if O0OO0OO0O00O in O0OOO0O00000:
            raise AionProtocolError('Device session is invalid and must be re-initialized.')
        return OOOO0OO00O00

    def parse_local_state_response(O0O0OOO000O0, OO0O000OOOOO: str) -> Any:
        if OO0O000OOOOO.strip() == '':
            return None
        try:
            OO00O0OO0000 = json.loads(OO0O000OOOOO)
        except json.JSONDecodeError:
            return OO0O000OOOOO
        if isinstance(OO00O0OO0000, dict) and 'res' in OO00O0OO0000:
            return OO00O0OO0000['res']
        return OO00O0OO0000

    def _build_primary_payload(OO000OO00O0O, O0000O00OOO0: dict[str, Any], O0O0O0OOO0OO: dict[str, Any], OO0O00OOOO00: dict[str, Any], OO0OO0O0000O: Any) -> str:
        OOO0OOOOO0O0 = O0000O00OOO0.get('control', {})
        OOO0O00O0OOO = OO000OO00O0O._timestamp_ms()
        OO0O0000O000 = OO000OO00O0O._action_id()
        O0OO000OOO0O = OOO0OOOOO0O0.get('gang_id')
        O0O0OOO00OO0 = 200 if OO0OO0O0000O == 'stop' else OO0OO0O0000O
        if bool(OO0O00OOOO00.get('json_mode')):
            OO00O0OO00OO: dict[str, Any] = {'w': O0O0OOO00OO0, 'src': _DEFAULT_PROTOCOL_SOURCE, 'usr': _DEFAULT_PROTOCOL_USER, 'actID': OO0O0000O000}
            if O0OO000OOO0O:
                OO00O0OO00OO['id'] = O0OO000OOO0O
            O000000O0O00 = json.dumps(OO00O0OO00OO, separators=(',', ':'))
        elif O0OO000OOO0O:
            O000000O0O00 = f'{O0OO000OOO0O}-{O0O0OOO00OO0}'
        else:
            O000000O0O00 = str(O0O0OOO00OO0)
        return f"{O0O0O0OOO0OO['ssid_suffix']},{OOO0O00O0OOO},{O000000O0O00}"

    def _resolve_ir_command(O000OO0OO00O, O000000O00O0: dict[str, Any], O00O0000OOOO: Any) -> dict[str, str]:
        if isinstance(O00O0000OOOO, str):
            O0O00OO00000 = O000000O00O0.get('control', {})
            O0O0OO0O0O0O = O0O00OO00000.get('commands', {})
            O0O00OOOOOO0 = O0O0OO0O0O0O.get(O00O0000OOOO)
            if isinstance(O0O00OOOOOO0, dict):
                return {'protocol': str(O0O00OOOOOO0['protocol']), 'size': str(O0O00OOOOOO0['size']), 'code': str(O0O00OOOOOO0['code'])}
            if O0O00OOOOOO0 is None:
                raise AionProtocolError(f"IR command '{O00O0000OOOO}' does not exist.")
            OOOOO0O0O0OO = O0O00OO00000.get('protocol')
            OOOOOOO0OO00 = O0O00OO00000.get('size')
            if OOOOO0O0O0OO is None or OOOOOOO0OO00 is None:
                raise AionProtocolError('IR command metadata is missing protocol or size information.')
            return {'protocol': str(OOOOO0O0O0OO), 'size': str(OOOOOOO0OO00), 'code': str(O0O00OOOOOO0)}
        OO0O000O000O = O000OO0OO00O._normalize_dict_payload(O00O0000OOOO, 'ir')
        OOO000O0O0O0 = {'protocol', 'size', 'code'}
        if not OOO000O0O0O0.issubset(OO0O000O000O.keys()):
            raise AionProtocolError('IR payload must contain protocol, size, and code.')
        return {'protocol': str(OO0O000O000O['protocol']), 'size': str(OO0O000O000O['size']), 'code': str(OO0O000O000O['code'])}

    def _normalize_dict_payload(OO00O0000OOO, OO00O0OOO000: Any, O0OOO000OO0O: str) -> dict[str, Any]:
        if not isinstance(OO00O0OOO000, dict):
            raise AionProtocolError(f'{O0OOO000OO0O} payload must be a JSON object.')
        return OO00O0OOO000

    def _with_action_metadata(OOOO000O0OO0, O0OOO0O000OO: dict[str, Any]) -> dict[str, Any]:
        OO00OO000O00 = dict(O0OOO0O000OO)
        OO00OO000O00.setdefault('actID', OOOO000O0OO0._action_id())
        OO00OO000O00.setdefault('src', _DEFAULT_PROTOCOL_SOURCE)
        OO00OO000O00.setdefault('usr', _DEFAULT_PROTOCOL_USER)
        return OO00OO000O00

    def _build_json_payload(O0O00O00O00O, O00O0O0000O0: str, O000OOOOOOOO: dict[str, Any]) -> str:
        return f"{O00O0O0000O0},{O0O00O00O00O._timestamp_ms()},{json.dumps(O000OOOOOOOO, separators=(',', ':'))}"

    def _merge_dict(OO00000O0000, OO0O0O000O0O: dict[str, Any], O000O0O0OOO0: dict[str, Any]) -> dict[str, Any]:
        O000O00OO0OO = dict(OO0O0O000O0O)
        for OOO0O00OOO00, O000O000000O in O000O0O0OOO0.items():
            if isinstance(O000O000000O, dict) and isinstance(O000O00OO0OO.get(OOO0O00OOO00), dict):
                O000O00OO0OO[OOO0O00OOO00] = OO00000O0000._merge_dict(O000O00OO0OO[OOO0O00OOO00], O000O000000O)
            else:
                O000O00OO0OO[OOO0O00OOO00] = O000O000000O
        return O000O00OO0OO

    def _encrypt(O00O0O0OO0O0, OOO00OOO0OOO: str, O0000OO0O000: str) -> tuple[str, str]:
        try:
            OOOOOOOOOO0O = secrets.token_bytes(16)
            OOOO0O000OO0 = AES.new(bytes.fromhex(O0000OO0O000), AES.MODE_CBC, OOOOOOOOOO0O)
            OOO0O00O00OO = OOOO0O000OO0.encrypt(pad(OOO00OOO0OOO.encode('utf-8'), AES.block_size))
        except ValueError as error:
            raise AionProtocolError('Device encryption key is invalid.') from error
        return (base64.b64encode(OOO0O00O00OO).decode('ascii'), OOOOOOOOOO0O.hex())

    def _decrypt(OO0O0OOO0O00, OOOOO0OOO00O: str, OOO00OOO00O0: str, OO00OOO0OOOO: str) -> str:
        try:
            O00OOO000000 = AES.new(bytes.fromhex(OO00OOO0OOOO), AES.MODE_CBC, bytes.fromhex(OOO00OOO00O0))
            O0OOO0OO0O0O = O00OOO000000.decrypt(base64.b64decode(OOOOO0OOO00O))
            return unpad(O0OOO0OO0O0O, AES.block_size).decode('utf-8')
        except (ValueError, TypeError) as error:
            raise AionProtocolError('Encrypted device response could not be decrypted.') from error

    def _timestamp_ms(O0O0OO0OOOO0) -> int:
        return int(time.time() * 1000)

    def _action_id(OO0OO000O0OO) -> str:
        return secrets.token_hex(3)