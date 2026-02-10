from pathlib import Path

# Расширенный список расширений файлов
file_extensions = {
    'image': [
        'jpg', 'png', 'bmp', 'ai', 'psd', 'ico', 'jpeg', 'ps', 'svg',
        'tif', 'tiff', 'gif', 'webp', 'raw', 'cr2', 'nef', 'orf', 'sr2'
    ],
    'video': [
        'mp4', 'mov', 'avi', 'mkv', 'wmv', '3gp', '3g2', 'mpg', 'mpeg',
        'm4v', 'h264', 'flv', 'rm', 'swf', 'vob', 'webm', 'ogv', 'ts',
        'mts', 'm2ts', 'divx'
    ],
    'audio': [
        'mp3', 'wav', 'ogg', 'flac', 'aif', 'mid', 'midi', 'mpa', 'wma',
        'wpl', 'cda', 'aac', 'm4a', 'opus', 'ape', 'alac'
    ],
    'archive': [
        'zip', 'rar', '7z', 'z', 'gz', 'rpm', 'arj', 'pkg', 'deb', 'tar',
        'bz2', 'xz', 'iso', 'dmg', 'cab'
    ],
    'documents': [
        'pdf', 'txt', 'doc', 'docx', 'rtf', 'tex', 'wpd', 'odt',
        'xlsx', 'xls', 'xlsm', 'ods', 'ppt', 'pptx', 'odp',
        'csv', 'xml', 'json', 'md'
    ],
    'code': [
        'py', 'js', 'java', 'cpp', 'c', 'h', 'cs', 'php', 'rb', 'go',
        'rs', 'swift', 'kt', 'html', 'css', 'scss', 'sass', 'ts', 'jsx',
        'tsx', 'vue', 'sql', 'sh', 'bat', 'ps1'
    ],
    'executable': [
        'exe', 'msi', 'app', 'apk', 'jar', 'dll', 'sys'
    ],
    'ebooks': [
        'epub', 'mobi', 'azw', 'azw3', 'fb2', 'djvu'
    ],
    'data': [
        'sql', 'sqlite', 'sqlite3', 'db', 'dbf', 'mdb', 'accdb',
        'dat', 'log', 'sav'
    ],
    'fonts': [
        'ttf', 'otf', 'woff', 'woff2', 'eot', 'fon'
    ],
    'cad': [
        '3ds', 'dwg', 'dxf', 'step', 'stp', 'iges', 'igs', 'stl', 'obj'
    ],
}

home_directory = Path.home()

destinations = {
    "image": home_directory / "Pictures",
    "audio": home_directory / "Music",
    "video": home_directory / "Videos",
    "documents": home_directory / "Documents",
    "archive": home_directory / "Documents" / "Archives",
    "code": home_directory / "Documents" / "Code",
    "executable": home_directory / "Downloads" / "Programs",
    "ebooks": home_directory / "Documents" / "Ebooks",
    "data": home_directory / "Documents" / "Data",
    "fonts": home_directory / "AppData" / "Local" / "Microsoft" / "Windows" / "Fonts",
    "cad": home_directory / "Documents" / "CAD",
}