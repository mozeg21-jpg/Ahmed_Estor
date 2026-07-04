import os

def parse_yaml_file(file_path):
    """
    A simple, robust pure-Python YAML parser for reading provider configs.
    """
    if not os.path.exists(file_path):
        return {'providers': []}
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception as e:
        print(f"Error reading file {file_path}: {e}")
        return {'providers': []}

    data = {'providers': []}
    current_provider = None
    
    for line in content.splitlines():
        # Remove comments
        if '#' in line:
            line = line.split('#', 1)[0]
        
        stripped = line.strip()
        if not stripped:
            continue
            
        # Check if starting a new provider entry
        if stripped.startswith('-'):
            if current_provider is not None:
                data['providers'].append(current_provider)
            current_provider = {}
            line_content = stripped[1:].strip()
        else:
            line_content = stripped
            
        if ':' in line_content:
            key, val = line_content.split(':', 1)
            key = key.strip()
            val = val.strip()
            if not val:
                continue
            
            # strip outer quotes if present
            if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                val = val[1:-1]
                
            # type conversion
            val_lower = val.lower()
            if val_lower == 'true':
                val = True
            elif val_lower == 'false':
                val = False
            elif val_lower == 'null' or val_lower == 'none':
                val = None
            else:
                try:
                    if '.' in val:
                        val = float(val)
                    else:
                        val = int(val)
                except ValueError:
                    pass # keep as string
                    
            if current_provider is not None:
                current_provider[key] = val
                
    if current_provider is not None:
        data['providers'].append(current_provider)
        
    return data

def dump_yaml_file(file_path, data):
    """
    A simple, robust pure-Python YAML writer for saving provider configs.
    """
    try:
        lines = []
        lines.append("providers:")
        providers = data.get('providers', [])
        for p in providers:
            fields = list(p.items())
            if not fields:
                continue
            
            first_key, first_val = fields[0]
            # format value
            if isinstance(first_val, bool):
                val_str = str(first_val).lower()
            elif first_val is None:
                val_str = "null"
            elif isinstance(first_val, (int, float)):
                val_str = str(first_val)
            else:
                val_str = f'"{first_val}"'
                
            lines.append(f"  - {first_key}: {val_str}")
            
            for k, v in fields[1:]:
                if isinstance(v, bool):
                    v_str = str(v).lower()
                elif v is None:
                    v_str = "null"
                elif isinstance(v, (int, float)):
                    v_str = str(v)
                else:
                    v_str = f'"{v}"'
                lines.append(f"    {k}: {v_str}")
                
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines) + '\n')
        return True
    except Exception as e:
        print(f"Error writing yaml file {file_path}: {e}")
        return False
