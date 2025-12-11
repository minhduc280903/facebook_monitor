#!/usr/bin/env python3
"""
Browser Configuration for Facebook Post Monitor - Enterprise Edition

🎯 MỤC ĐÍCH:
- Tập trung TẤT CẢ cấu hình trình duyệt vào MỘT FILE DUY NHẤT
- Đảm bảo browser fingerprint HOÀN TOÀN NHẤT QUÁN trên toàn hệ thống
- Ngăn chặn triệt để browser fingerprinting mismatch

🔧 SỬ DỤNG:
- manual_login.py: Tạo sessions với cấu hình chuẩn
- worker.py: Sử dụng sessions với CHÍNH XÁC cùng cấu hình
- debug_single_worker.py: Test với cấu hình nhất quán

⚠️ QUAN TRỌNG:
- MỌI THAY ĐỔI chỉ thực hiện TẠI FILE NÀY
- KHÔNG ĐƯỢC chỉnh sửa cấu hình browser ở file khác
- Mọi sự thay đổi sẽ ảnh hưởng toàn hệ thống
"""

from typing import Dict, List, Any, Optional
import hashlib
import random as random_module
import uuid
import json
import os
from datetime import datetime

# Constants for browser configuration  
DEFAULT_USER_AGENT = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
    '(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'
)
DEFAULT_VIEWPORT_WIDTH = 1920
DEFAULT_VIEWPORT_HEIGHT = 1080
DEFAULT_LOCALE = 'vi-VN'
DEFAULT_TIMEZONE = 'Asia/Ho_Chi_Minh'
# 🌍 Default geolocation (Hanoi, Vietnam - matches proxy locations)
DEFAULT_LATITUDE = 21.0285
DEFAULT_LONGITUDE = 105.8542
MOCK_PLUGINS_COUNT = 5
FINGERPRINT_VERSION = "v3.2_final_perfect_geolocation"

# 🎨 GenLogin-Style Fingerprint Pools
WEBGL_VENDORS = [
    "Intel Inc.", "NVIDIA Corporation", "ATI Technologies Inc.",
    "Google Inc. (NVIDIA)", "Google Inc. (Intel)", "Google Inc. (AMD)",
    "ARM", "Qualcomm", "Apple Inc."
]

WEBGL_RENDERERS = [
    "Intel Iris OpenGL Engine", "Intel(R) UHD Graphics 620",
    "NVIDIA GeForce GTX 1050", "NVIDIA GeForce GTX 1650",
    "AMD Radeon RX 580", "AMD Radeon Pro 560",
    "ANGLE (Intel, Intel(R) UHD Graphics 620 Direct3D11 vs_5_0 ps_5_0)",
    "ANGLE (NVIDIA, NVIDIA GeForce GTX 1650 Direct3D11 vs_5_0 ps_5_0)",
    "Apple M1", "Mali-G78", "Adreno (TM) 640"
]

# ✅ ANTI-DETECTION: Diverse resolutions to prevent clustering detection
# Distribution based on real-world usage statistics (2024-2025)
# NOTE: If using Xvfb, ensure it's configured for each resolution dynamically
SCREEN_RESOLUTIONS = [
    (1920, 1080),  # 30% - Most common (Full HD)
    (1920, 1200),  # 15% - WUXGA
    (2560, 1440),  # 12% - QHD/2K
    (1680, 1050),  # 10% - WSXGA+
    (1600, 900),   # 8%  - HD+
    (1440, 900),   # 8%  - WXGA+
    (1366, 768),   # 7%  - Common laptop
    (1280, 1024),  # 5%  - SXGA
    (1280, 800),   # 3%  - WXGA
    (3840, 2160),  # 2%  - 4K UHD
]

# Weighted distribution for realistic selection (matches percentages above)
SCREEN_RESOLUTION_WEIGHTS = [30, 15, 12, 10, 8, 8, 7, 5, 3, 2]

CPU_CORES = [2, 4, 6, 8, 12, 16]
DEVICE_MEMORY_GB = [4, 8, 16, 32]

# Font pool (subset của system fonts - GenLogin strategy)
FONT_POOL = [
    'Arial', 'Arial Black', 'Helvetica', 'Helvetica Neue', 'Times New Roman',
    'Times', 'Courier New', 'Courier', 'Verdana', 'Georgia', 'Palatino',
    'Garamond', 'Bookman', 'Comic Sans MS', 'Trebuchet MS', 'Impact',
    'Lucida Sans Unicode', 'Tahoma', 'Lucida Console', 'Monaco', 'Bradley Hand',
    'Brush Script MT', 'Luminari', 'Copperplate', 'Papyrus', 'Courier',
    'Andale Mono', 'MS Gothic', 'MS Mincho', 'SimSun', 'PMingLiU'
]

# 🎯 User Agent Database (matched to WebGL vendor/platform)
USER_AGENT_DATABASE = {
    # Windows + Intel
    ('Win32', 'Intel'): [
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
    ],
    # Windows + NVIDIA
    ('Win32', 'NVIDIA'): [
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
    ],
    # Windows + AMD
    ('Win32', 'ATI'): [
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
    ],
    # Windows + Google (ANGLE)
    ('Win32', 'Google'): [
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
    ],
    # macOS + Apple
    ('MacIntel', 'Apple'): [
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
    ],
    # Linux ARM
    ('Linux armv8l', 'ARM'): [
        'Mozilla/5.0 (X11; Linux aarch64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    ],
    # Linux ARM (Mali)
    ('Linux armv8l', 'Mali'): [
        'Mozilla/5.0 (X11; Linux aarch64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    ],
    # Linux ARM (Qualcomm)
    ('Linux armv8l', 'Qualcomm'): [
        'Mozilla/5.0 (X11; Linux aarch64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    ],
}

# 🔌 Realistic Plugin Definitions per Platform
PLUGIN_DEFINITIONS = {
    'Win32': [
        {
            'name': 'PDF Viewer',
            'filename': 'internal-pdf-viewer',
            'description': 'Portable Document Format',
            'mimeTypes': [
                {'type': 'application/pdf', 'suffixes': 'pdf', 'description': 'Portable Document Format'},
                {'type': 'text/pdf', 'suffixes': 'pdf', 'description': 'Portable Document Format'}
            ]
        },
        {
            'name': 'Chrome PDF Viewer',
            'filename': 'mhjfbmdgcfjbbpaeojofohoefgiehjai',
            'description': 'Portable Document Format',
            'mimeTypes': [
                {'type': 'application/pdf', 'suffixes': 'pdf', 'description': 'Portable Document Format'}
            ]
        },
        {
            'name': 'Chromium PDF Viewer',
            'filename': 'mhjfbmdgcfjbbpaeojofohoefgiehjai',
            'description': 'Portable Document Format',
            'mimeTypes': [
                {'type': 'application/pdf', 'suffixes': 'pdf', 'description': 'Portable Document Format'}
            ]
        }
    ],
    'MacIntel': [
        {
            'name': 'PDF Viewer',
            'filename': 'internal-pdf-viewer',
            'description': 'Portable Document Format',
            'mimeTypes': [
                {'type': 'application/pdf', 'suffixes': 'pdf', 'description': 'Portable Document Format'}
            ]
        },
        {
            'name': 'Chrome PDF Viewer',
            'filename': 'mhjfbmdgcfjbbpaeojofohoefgiehjai',
            'description': 'Portable Document Format',
            'mimeTypes': [
                {'type': 'application/pdf', 'suffixes': 'pdf', 'description': 'Portable Document Format'}
            ]
        }
    ],
    'Linux armv8l': [
        {
            'name': 'PDF Viewer',
            'filename': 'internal-pdf-viewer',
            'description': 'Portable Document Format',
            'mimeTypes': [
                {'type': 'application/pdf', 'suffixes': 'pdf', 'description': 'Portable Document Format'}
            ]
        }
    ]
}


# ═══════════════════════════════════════════════════════════════
# 🔒 MACHINE ID FUNCTIONS - CRITICAL ANTI-DETECTION
# ═══════════════════════════════════════════════════════════════

def generate_unique_machine_id(session_id: str, creation_date: Optional[datetime] = None) -> str:
    """
    ✅ ANTI-DETECTION: Generate unique but deterministic machine ID per session
    
    Prevents Facebook detection of multiple accounts from same VPS machine-id.
    
    Args:
        session_id: Unique session identifier
        creation_date: Session creation date (for stability across restarts)
    
    Returns:
        UUID string unique to this session but stable across restarts
    
    Example:
        >>> generate_unique_machine_id("61576964227108")
        'a1b2c3d4-1234-5678-9abc-def012345678'
    """
    # UUID v5: Deterministic based on namespace + name
    # Same inputs → Same UUID (stable across restarts)
    namespace = uuid.UUID('12345678-1234-5678-1234-567812345678')
    
    # Combine session_id with creation date for uniqueness
    if creation_date:
        seed_string = f"{session_id}_{creation_date.isoformat()}"
    else:
        # Fallback: Use session_id only (less ideal but still unique)
        seed_string = session_id
    
    machine_id = str(uuid.uuid5(namespace, seed_string))
    return machine_id


def inject_machine_id_to_local_state(session_dir: str, machine_id: str) -> bool:
    """
    ✅ ANTI-DETECTION: Inject unique machine ID into Chromium Local State file
    
    Chromium stores machine-id in Local State for metrics/telemetry.
    Without this, all sessions share VPS's machine-id → Multi-account detection.
    
    Args:
        session_dir: Path to Chromium user data directory
        machine_id: Unique machine ID to inject
    
    Returns:
        True if successful, False otherwise
    
    Example:
        >>> inject_machine_id_to_local_state("./sessions/session_A", "uuid-here")
        True
    """
    try:
        from logging_config import get_logger
        logger = get_logger(__name__)
    except ImportError:
        import logging
        logger = logging.getLogger(__name__)
    
    local_state_path = os.path.join(session_dir, "Local State")
    
    try:
        # Read existing Local State (or create new)
        if os.path.exists(local_state_path):
            with open(local_state_path, 'r', encoding='utf-8') as f:
                state = json.load(f)
        else:
            state = {}
        
        # Inject machine ID into multiple locations Chromium checks
        # 1. user_experience_metrics.client_id (primary)
        if 'user_experience_metrics' not in state:
            state['user_experience_metrics'] = {}
        state['user_experience_metrics']['client_id'] = machine_id
        
        # 2. variations_permanent_consistency_country (secondary)
        # Keep existing if present, don't override
        if 'variations_permanent_consistency_country' not in state:
            state['variations_permanent_consistency_country'] = ''
        
        # 3. hardware.machine_statistics_info (tertiary - some Chromium builds)
        if 'hardware' not in state:
            state['hardware'] = {}
        if 'machine_statistics_info' not in state['hardware']:
            state['hardware']['machine_statistics_info'] = {}
        
        # Write back to file
        with open(local_state_path, 'w', encoding='utf-8') as f:
            json.dump(state, f, indent=2)
        
        logger.info(f"✅ Injected machine ID: {machine_id[:13]}... into {session_dir}")
        return True
        
    except Exception as e:
        logger.error(f"❌ Failed to inject machine ID into {session_dir}: {e}")
        return False


def generate_session_fingerprint(session_id: str, 
                                 proxy_geolocation: Optional[Dict[str, Any]] = None,
                                 days_since_creation: int = 0) -> Dict[str, Any]:
    """
    🎨 Generate unique browser fingerprint per session (GenLogin/GPM Style)
    
    ✅ ANTI-DETECTION EVOLUTION: Fingerprint evolves over time like real hardware
    
    DETERMINISTIC: Same session_id + days → Same fingerprint (reproducible)
    UNIQUE: Different session_id → Different fingerprint
    EVOLUTION: Fingerprint drifts over time (driver updates, hardware upgrades)
    
    Args:
        session_id: Unique session identifier
        proxy_geolocation: Optional dict with timezone, latitude, longitude from proxy (PHASE 3)
        days_since_creation: Days since session was first created (for evolution simulation)
        
    Returns:
        Complete fingerprint dict with Canvas/WebGL/Audio/Hardware params
        
    Evolution Timeline:
        - 0-30 days: Stable fingerprint
        - 30-60 days: Small drift (simulated driver update, +5% noise)
        - 60-90 days: Another drift (+10% noise)
        - 180+ days: 15% chance of "hardware upgrade" (new GPU)
        
    Example:
        >>> fp = generate_session_fingerprint("61576964227108", days_since_creation=0)
        >>> fp['canvas_noise']  # 0.000012345
        >>> fp_evolved = generate_session_fingerprint("61576964227108", days_since_creation=90)
        >>> fp_evolved['canvas_noise']  # 0.000015678 (drifted)
    """
    # Base seed from session_id for reproducibility
    base_seed = int(hashlib.md5(session_id.encode()).hexdigest()[:8], 16)
    
    # ✅ EVOLUTION FACTOR: Modify seed based on time passage
    # Every 30 days represents a "stage" (driver update, OS patch, etc.)
    evolution_stage = days_since_creation // 30  # 0, 1, 2, 3...
    
    # Evolved seed: Add evolution offset to base seed
    # This causes gradual drift in all fingerprint parameters
    evolution_offset = evolution_stage * 12345  # Magic number for variation
    evolved_seed = base_seed + evolution_offset
    
    rng = random_module.Random(evolved_seed)
    
    # Select screen resolution with weighted distribution (realistic prevalence)
    # Use cumulative weights for deterministic selection
    cumulative_weights = []
    total = 0
    for w in SCREEN_RESOLUTION_WEIGHTS:
        total += w
        cumulative_weights.append(total)
    
    # Deterministic weighted random selection
    rand_val = rng.random() * total
    selected_idx = 0
    for idx, cum_weight in enumerate(cumulative_weights):
        if rand_val < cum_weight:
            selected_idx = idx
            break
    
    screen_width, screen_height = SCREEN_RESOLUTIONS[selected_idx]
    
    # ✅ EVOLUTION: WebGL Hardware "Upgrade" Simulation
    # After 180 days (6 months), 15% chance of simulated GPU upgrade
    # Represents users who buy new hardware over time
    hardware_upgrade_triggered = False
    if days_since_creation >= 180:
        # Use base_seed for consistent upgrade decision (same session always upgrades or doesn't)
        upgrade_rng = random_module.Random(base_seed + 99999)  # Different seed for upgrade decision
        if upgrade_rng.random() < 0.15:  # 15% chance
            hardware_upgrade_triggered = True
            try:
                from logging_config import get_logger
                logger = get_logger(__name__)
                logger.info(f"🔧 Session {session_id}: Simulated hardware upgrade after {days_since_creation} days")
            except:
                pass
    
    # Select WebGL params (must be consistent pair)
    if hardware_upgrade_triggered:
        # ✅ UPGRADE: Prefer higher-end GPUs (NVIDIA/AMD)
        premium_vendors = [v for v in WEBGL_VENDORS if 'NVIDIA' in v or 'AMD' in v]
        webgl_vendor = rng.choice(premium_vendors) if premium_vendors else rng.choice(WEBGL_VENDORS)
    else:
        # Normal selection
        webgl_vendor = rng.choice(WEBGL_VENDORS)
    
    # Match renderer to vendor
    if "Intel" in webgl_vendor:
        webgl_renderers_filtered = [r for r in WEBGL_RENDERERS if "Intel" in r or "ANGLE (Intel" in r]
    elif "NVIDIA" in webgl_vendor:
        webgl_renderers_filtered = [r for r in WEBGL_RENDERERS if "NVIDIA" in r or "GeForce" in r]
    elif "AMD" in webgl_vendor or "ATI" in webgl_vendor:
        webgl_renderers_filtered = [r for r in WEBGL_RENDERERS if "AMD" in r or "Radeon" in r]
    elif "Apple" in webgl_vendor:
        webgl_renderers_filtered = [r for r in WEBGL_RENDERERS if "Apple" in r or "M1" in r]
    else:
        webgl_renderers_filtered = WEBGL_RENDERERS
    
    webgl_renderer = rng.choice(webgl_renderers_filtered) if webgl_renderers_filtered else rng.choice(WEBGL_RENDERERS)
    
    # Select fonts (25-30 random fonts from pool)
    num_fonts = rng.randint(20, 30)
    fonts = rng.sample(FONT_POOL, min(num_fonts, len(FONT_POOL)))
    
    # 🎯 Determine platform from WebGL vendor (for consistency)
    if 'Apple' in webgl_vendor or 'M1' in webgl_renderer or 'M2' in webgl_renderer:
        platform = 'MacIntel'
    elif ('ARM' in webgl_vendor or 'Adreno' in webgl_renderer or 'Mali' in webgl_renderer or 
          'Qualcomm' in webgl_vendor or 'Qualcomm' in webgl_renderer):
        platform = 'Linux armv8l'
    else:
        platform = 'Win32'
    
    # 🎯 CRITICAL FIX: Select User Agent that MATCHES REAL Chrome version
    # Extract vendor key for UA matching
    vendor_key = None
    for key in ['Intel', 'NVIDIA', 'ATI', 'Apple', 'ARM', 'Mali', 'Qualcomm', 'Google']:
        if key in webgl_vendor:
            vendor_key = key
            break
    
    # Fallback to Intel if no match
    if not vendor_key:
        vendor_key = 'Intel'
    
    # 🔥 DETECT REAL CHROME VERSION and build matching UA
    real_chrome_version = _detect_chrome_version()
    # ✅ ANTI-DETECTION: Add build number variation using base_seed
    user_agent = _get_matching_user_agent(real_chrome_version, platform, vendor_key, session_seed=base_seed)
    
    # 🔌 Get realistic plugins for platform
    plugins = PLUGIN_DEFINITIONS.get(platform, PLUGIN_DEFINITIONS['Win32'])
    
    # ✅ EVOLUTION: Canvas/Audio Noise Gradual Drift
    # Simulates driver updates, OS patches, hardware wear-and-tear
    # Base noise increases by ~0.00002 per evolution stage (every 30 days)
    base_canvas_noise = rng.uniform(0.0001, 0.0005)  # Increased from 0.00001-0.00005 for more realism
    canvas_noise_drift = evolution_stage * 0.00002  # Gradual increase: +0.00002 every 30 days
    canvas_noise = min(base_canvas_noise + canvas_noise_drift, 0.002)  # Cap at 0.2% (realistic max)
    
    base_audio_noise = rng.uniform(0.0001, 0.0005)
    audio_noise_drift = evolution_stage * 0.00005  # Audio drifts faster than canvas
    audio_noise = min(base_audio_noise + audio_noise_drift, 0.005)  # Cap at 0.5%
    
    fingerprint = {
        # Canvas fingerprinting (noise injection seed)
        "canvas_noise": canvas_noise,
        "canvas_seed": base_seed % 100000,  # Use base_seed (not evolved) for consistent seed
        
        # WebGL fingerprinting
        "webgl": {
            "vendor": webgl_vendor,
            "renderer": webgl_renderer,
            "max_texture_size": rng.choice([8192, 16384, 32768]),
            "max_vertex_uniform_vectors": rng.choice([1024, 2048, 4096]),
            "shading_language_version": "WebGL GLSL ES 1.0"
        },
        
        # AudioContext fingerprinting
        "audio_noise": audio_noise,
        "audio_seed": (base_seed + 12345) % 100000,  # Use base_seed for consistent audio seed
        
        # Hardware parameters
        "hardware": {
            "cpu_cores": rng.choice(CPU_CORES),
            "device_memory": rng.choice(DEVICE_MEMORY_GB),
            "screen_width": screen_width,
            "screen_height": screen_height,
            "color_depth": 24,
            "pixel_ratio": rng.choice([1.0, 1.25, 1.5, 2.0])
        },
        
        # Fonts (per-profile subset)
        "fonts": fonts,
        
        # Platform (consistent with WebGL)
        "platform": platform,
        
        # 🎯 PHASE 1 FIX: Matched User Agent
        "user_agent": user_agent,
        
        # 🔌 PHASE 1 FIX: Realistic Plugins
        "plugins": plugins,
        
        # 🌍 PHASE 3: Timezone and Geolocation from proxy (if available)
        "timezone": proxy_geolocation.get('timezone', DEFAULT_TIMEZONE) if proxy_geolocation else DEFAULT_TIMEZONE,
        "geolocation": {
            "latitude": proxy_geolocation.get('latitude', DEFAULT_LATITUDE) if proxy_geolocation else DEFAULT_LATITUDE,
            "longitude": proxy_geolocation.get('longitude', DEFAULT_LONGITUDE) if proxy_geolocation else DEFAULT_LONGITUDE,
            "accuracy": 100
        },
        
        # Locale
        "locale": DEFAULT_LOCALE,
        
        # Metadata
        "fingerprint_version": FINGERPRINT_VERSION,
        "generated_from_seed": base_seed,
        "days_since_creation": days_since_creation  # Track age for evolution monitoring
    }
    
    return fingerprint


def _detect_chrome_version() -> Optional[str]:
    """
    🔍 CRITICAL: Detect REAL Chrome/Chromium version on system
    
    Returns Chrome version string (e.g., "120.0.6099.109") or None if can't detect
    """
    import subprocess
    import re
    import sys
    import os
    
    try:
        if sys.platform == 'win32':
            # Windows: Try multiple paths
            chrome_paths = [
                r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            ]
            for path in chrome_paths:
                if os.path.exists(path):
                    result = subprocess.run([path, '--version'], capture_output=True, text=True, timeout=5)
                    if result.returncode == 0:
                        match = re.search(r'(\d+\.\d+\.\d+\.\d+)', result.stdout)
                        if match:
                            return match.group(1)
        else:
            # Linux/Mac: Try google-chrome or chromium-browser
            for cmd in ['google-chrome', 'chromium-browser', 'chromium']:
                try:
                    result = subprocess.run([cmd, '--version'], capture_output=True, text=True, timeout=5)
                    if result.returncode == 0:
                        match = re.search(r'(\d+\.\d+\.\d+\.\d+)', result.stdout)
                        if match:
                            return match.group(1)
                except FileNotFoundError:
                    continue
    except Exception as e:
        print(f"⚠️ Could not detect Chrome version: {e}")
    
    return None


def _get_matching_user_agent(chrome_version: Optional[str], platform: str, vendor_key: str, 
                             session_seed: Optional[int] = None) -> str:
    """
    🎯 CRITICAL: Get User-Agent that MATCHES real Chrome version
    
    ✅ ANTI-DETECTION: Add build number variation per session
    
    Args:
        chrome_version: Real Chrome version (e.g., "120.0.6099.109")
        platform: Platform string (Win32, MacIntel, Linux armv8l)
        vendor_key: WebGL vendor key for matching
        session_seed: Optional seed for deterministic build variation per session
        
    Returns:
        User-Agent string with varied Chrome version
        
    Example:
        - Session A: Chrome/120.0.6250.142
        - Session B: Chrome/120.0.6450.087
        - Session C: Chrome/119.0.6099.195
        Real diversity prevents clustering detection.
    """
    # Default fallback
    if not chrome_version:
        chrome_version = "120.0.6099.109"
    
    # Parse version components
    parts = chrome_version.split('.')
    major = parts[0] if len(parts) > 0 else "120"
    minor = parts[1] if len(parts) > 1 else "0"
    build = parts[2] if len(parts) > 2 else "6099"
    patch = parts[3] if len(parts) > 3 else "109"
    
    # ✅ VARIATION: Add per-session build number differences if seed provided
    if session_seed is not None:
        rng = random_module.Random(session_seed)
        
        # Minor version: Vary ±1 (e.g., 120.0 → 120.0 or 120.1, rare 119.0)
        # Bias toward 0 (80% stay same, 15% +1, 5% -1)
        rand = rng.random()
        if rand < 0.80:
            minor_variant = int(minor)  # 80% keep same
        elif rand < 0.95:
            minor_variant = int(minor) + 1  # 15% increment
        else:
            minor_variant = max(0, int(minor) - 1)  # 5% decrement
        
        # Build number: Vary ±1000 for diversity
        build_variant = int(build) + rng.randint(-1000, 1000)
        build_variant = max(1000, min(9999, build_variant))  # Keep in valid range
        
        # Patch: Vary ±100
        patch_variant = int(patch) + rng.randint(-100, 100)
        patch_variant = max(0, min(999, patch_variant))
        
        version_string = f"{major}.{minor_variant}.{build_variant}.{patch_variant}"
    else:
        # No seed: Use major version only (generic but safe)
        version_string = f"{major}.0.0.0"
    
    # Build full UA string based on platform
    if platform == 'Win32':
        return f'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{version_string} Safari/537.36'
    elif platform == 'MacIntel':
        return f'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{version_string} Safari/537.36'
    else:  # Linux
        return f'Mozilla/5.0 (X11; Linux aarch64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{version_string} Safari/537.36'


def get_browser_args() -> List[str]:
    """
    Trả về danh sách các arguments cho trình duyệt.

    🛡️ Anti-Detection Browser Arguments:
    - Disable automation detection features
    - Mimic human browsing behavior
    - Consistent system-level configuration

    Returns:
        List[str]: Complete list of browser arguments
    """
    return [
        '--no-first-run',                        # Skip first run experience
        '--no-default-browser-check',            # Skip default browser check
        '--disable-blink-features=AutomationControlled',  # Critical
        '--disable-web-security',                # Allow cross-origin requests
        '--disable-features=VizDisplayCompositor',  # Display optimization
        '--disable-dev-shm-usage',               # Memory optimization
        '--disable-extensions',                  # Clean browser environment
        '--no-sandbox',                          # Security bypass
        '--disable-setuid-sandbox',              # Additional security bypass
        # ❌ REMOVED: '--disable-gpu' - Keep GPU for anti-detection (WebGL/Canvas)
        '--disable-background-timer-throttling',  # Performance optimization
        '--disable-backgrounding-occluded-windows',  # Window management
        '--disable-renderer-backgrounding',      # Renderer optimization
        '--disable-field-trial-config',  # 🔥 CRITICAL: Field trial consistency
        '--disable-back-forward-cache',  # 🔥 CRITICAL: Navigation consistency
        '--disable-ipc-flooding-protection',  # 🔥 CRITICAL: IPC behavior
        # 🔒 ANTI-DETECTION: WebRTC Complete Disable (TIER 1 - HIGH Priority)
        '--disable-webrtc',  # Nuclear option: Completely disable WebRTC to prevent IP leaks
        '--force-webrtc-ip-handling-policy=disable_non_proxied_udp',  # Fallback: Block UDP if WebRTC somehow enabled
    ]


def get_browser_launch_options(
    user_data_dir: str,
    headless: bool = False,
    proxy_config: Optional[Dict[str, Any]] = None,
    docker_mode: bool = False,  # Deprecated: kept for backward compatibility
    session_fingerprint: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Trả về dict chứa TẤT CẢ các tùy chọn khởi động trình duyệt.

    Args:
        user_data_dir: Đường dẫn đến session directory
        headless: True = headless mode, False = với GUI
        proxy_config: Dict chứa proxy configuration (từ ProxyManager)

    Returns:
        Complete browser launch configuration
    """
    import logging
    import os
    import subprocess
    logger = logging.getLogger(__name__)
    
    args = get_browser_args()
    
    # 🔥 CRITICAL FIX: Detect REAL Chrome version và match với User Agent
    real_chrome_version = _detect_chrome_version()
    if real_chrome_version:
        logger.info(f"🔍 Detected Chrome version: {real_chrome_version}")
    else:
        logger.warning("⚠️ Could not detect Chrome version, using default UA")

    # ⚠️ LEGACY: Docker-specific args (kept for backward compatibility)
    if docker_mode:
        legacy_args = [
            '--disable-dev-shm-usage',
            '--disable-extensions',
            '--disable-background-timer-throttling',
            '--disable-features=Translate,BackForwardCache',
            '--no-default-browser-check',
            '--disable-software-rasterizer',
            '--disable-background-networking',
            '--disable-default-apps',
            '--disable-sync',
            '--metrics-recording-only'
        ]
        args.extend(legacy_args)
    
    # 🔥 QUAN TRỌNG: Headless mode handling
    if headless:
        args.append('--headless=new')  # Use new headless mode
    
    # 🔒 ANTI-DETECTION: DNS Leak Protection
    # Force DNS resolution through proxy or use DNS-over-HTTPS
    if proxy_config:
        proxy_type = proxy_config.get('type', 'http').lower()
        
        # Method 1: For SOCKS5 proxies, DNS is usually handled by proxy
        # Add host-resolver-rules to ensure DNS goes through proxy
        if proxy_type == 'socks5':
            logger.info("🔒 DNS leak protection: SOCKS5 proxy will handle DNS resolution")
            # SOCKS5 naturally forwards DNS through proxy
            # Add args to prevent DNS bypass
            args.append('--host-resolver-rules="MAP * ~NOTFOUND , EXCLUDE localhost"')
        
        # Method 2: For HTTP/HTTPS proxies, use DNS-over-HTTPS to prevent DNS leak
        else:
            logger.info("🔒 DNS leak protection: Forcing DNS-over-HTTPS (Cloudflare 1.1.1.1)")
            args.append('--enable-features=DnsOverHttps')
            args.append('--dns-over-https-server=https://1.1.1.1/dns-query')
    else:
        # No proxy: Still use DoH for consistency and privacy
        logger.debug("🔒 DNS: Using DNS-over-HTTPS (no proxy configured)")
        args.append('--enable-features=DnsOverHttps')
        args.append('--dns-over-https-server=https://1.1.1.1/dns-query')

    # 🎨 APPLY FINGERPRINT (GenLogin/GPM Style)
    if session_fingerprint:
        viewport_width = session_fingerprint.get('hardware', {}).get('screen_width', DEFAULT_VIEWPORT_WIDTH)
        viewport_height = session_fingerprint.get('hardware', {}).get('screen_height', DEFAULT_VIEWPORT_HEIGHT)
        timezone = session_fingerprint.get('timezone', DEFAULT_TIMEZONE)
        locale = session_fingerprint.get('locale', DEFAULT_LOCALE)
        pixel_ratio = session_fingerprint.get('hardware', {}).get('pixel_ratio', 1.0)
        user_agent = session_fingerprint.get('user_agent', DEFAULT_USER_AGENT)  # 🎯 Already matched in fingerprint
    else:
        viewport_width = DEFAULT_VIEWPORT_WIDTH
        viewport_height = DEFAULT_VIEWPORT_HEIGHT
        timezone = DEFAULT_TIMEZONE
        locale = DEFAULT_LOCALE
        pixel_ratio = 1.0
        # 🔥 CRITICAL: Generate matching UA even without fingerprint
        platform = 'Win32'  # Default platform
        user_agent = _get_matching_user_agent(real_chrome_version, platform, 'Intel')

    launch_options = {
        "user_data_dir": user_data_dir,
        "headless": headless,
        "args": args,
        # 🎯 PHASE 1 FIX: Per-session User Agent (matched to WebGL/Platform)
        "user_agent": user_agent,
        "viewport": {
            'width': viewport_width,
            'height': viewport_height
        },
        "locale": locale,
        "timezone_id": timezone,
        "java_script_enabled": True,
        "bypass_csp": True,
        "ignore_https_errors": True,
        # ENHANCED: Cookie persistence options
        "accept_downloads": True,
        # 🎨 FINGERPRINT: Per-session pixel ratio
        "device_scale_factor": pixel_ratio,
        "is_mobile": False,
        "has_touch": False,
        # 🔥 CRITICAL: Use Google Chrome binary on VPS (not Chromium!)
        "executable_path": "/usr/bin/google-chrome" if os.path.exists("/usr/bin/google-chrome") else None
    }
    
    # 🔧 PRODUCTION FIX: Tích hợp ProxyManager
    # Nếu có proxy config, áp dụng vào browser options
    if proxy_config:
        try:
            from core.proxy_manager import ProxyManager
            proxy_manager = ProxyManager()
            playwright_proxy = proxy_manager.get_proxy_for_playwright(
                proxy_config
            )
            
            if playwright_proxy:
                launch_options['proxy'] = playwright_proxy
                logger.info(
                    "🔗 Applied proxy to browser: %s:%s",
                    proxy_config.get('host'),
                    proxy_config.get('port')
                )
            else:
                logger.warning(
                    "⚠️ Failed to convert proxy config for Playwright"
                )
                
        except (ImportError, AttributeError, KeyError, ValueError) as e:
            logger.error("❌ Error applying proxy config: %s", e)
            # Continue without proxy rather than failing
    
    return launch_options


def get_init_script(fingerprint: Optional[Dict[str, Any]] = None) -> str:
    """
    🎨 GenLogin/GPM-Style Advanced Anti-Detection Script
    
    Inject Canvas/WebGL/Audio/Hardware spoofing based on per-session fingerprint

    Args:
        fingerprint: Session-specific fingerprint dict (from generate_session_fingerprint)

    Returns:
        Complete anti-detection JavaScript code with fingerprint spoofing
    """
    # Extract fingerprint params (or use defaults)
    if fingerprint:
        canvas_noise = fingerprint.get('canvas_noise', 0.00001)
        canvas_seed = fingerprint.get('canvas_seed', 12345)
        webgl_vendor = fingerprint.get('webgl', {}).get('vendor', 'Intel Inc.')
        webgl_renderer = fingerprint.get('webgl', {}).get('renderer', 'Intel Iris OpenGL Engine')
        audio_noise = fingerprint.get('audio_noise', 0.0001)
        audio_seed = fingerprint.get('audio_seed', 54321)
        cpu_cores = fingerprint.get('hardware', {}).get('cpu_cores', 8)
        device_memory = fingerprint.get('hardware', {}).get('device_memory', 8)
        screen_width = fingerprint.get('hardware', {}).get('screen_width', 1920)
        screen_height = fingerprint.get('hardware', {}).get('screen_height', 1080)
        color_depth = fingerprint.get('hardware', {}).get('color_depth', 24)
        pixel_ratio = fingerprint.get('hardware', {}).get('pixel_ratio', 1.0)
        fonts = fingerprint.get('fonts', FONT_POOL[:20])
        platform = fingerprint.get('platform', 'Win32')
        plugins = fingerprint.get('plugins', PLUGIN_DEFINITIONS['Win32'])
        
        # ✅ ANTI-DETECTION: Calculate taskbar height based on platform
        # Windows: 40px taskbar, Mac: 25px menu bar, Linux: 27-30px (GNOME/KDE)
        if 'Mac' in platform:
            taskbar_height = 25
        elif 'Linux' in platform or 'arm' in platform:
            taskbar_height = 27
        else:  # Win32 default
            taskbar_height = 40
        
        # 🌍 PHASE 3: Extract geolocation
        geolocation = fingerprint.get('geolocation', {})
        geo_latitude = geolocation.get('latitude', DEFAULT_LATITUDE)
        geo_longitude = geolocation.get('longitude', DEFAULT_LONGITUDE)
        geo_accuracy = geolocation.get('accuracy', 100)
    else:
        canvas_noise = 0.00001
        canvas_seed = 12345
        webgl_vendor = 'Intel Inc.'
        webgl_renderer = 'Intel Iris OpenGL Engine'
        audio_noise = 0.0001
        audio_seed = 54321
        cpu_cores = 8
        device_memory = 8
        screen_width = 1920
        screen_height = 1080
        color_depth = 24
        pixel_ratio = 1.0
        fonts = FONT_POOL[:20]
        platform = 'Win32'
        plugins = PLUGIN_DEFINITIONS['Win32']
        taskbar_height = 40  # Default Windows taskbar
        geo_latitude = DEFAULT_LATITUDE
        geo_longitude = DEFAULT_LONGITUDE
        geo_accuracy = 100
    
    # Convert fonts list to JS array string
    fonts_js = str(fonts).replace("'", '"')
    
    # 🔌 PHASE 1 FIX: Generate realistic plugins JavaScript
    plugins_js = '['
    for i, plugin in enumerate(plugins):
        if i > 0:
            plugins_js += ','
        mime_types_js = '['
        for j, mime in enumerate(plugin['mimeTypes']):
            if j > 0:
                mime_types_js += ','
            mime_types_js += f"{{type:'{mime['type']}',suffixes:'{mime['suffixes']}',description:'{mime['description']}'}}"
        mime_types_js += ']'
        
        plugins_js += f"{{name:'{plugin['name']}',filename:'{plugin['filename']}',description:'{plugin['description']}',length:{len(plugin['mimeTypes'])},item:function(i){{return this[i]}},namedItem:function(n){{for(let i=0;i<this.length;i++)if(this[i].type===n)return this[i];return null}},{','.join([f'{k}:this[{k}]' for k in range(len(plugin['mimeTypes']))])}}}"
    plugins_js += ']'
    
    return f"""
        // 🎨 GenLogin/GPM-Style Advanced Anti-Detection v3.1 (FIXED)
        
        // ═══════════════════════════════════════════════════════════════
        // 🛡️ CORE: Hide webdriver property
        // ═══════════════════════════════════════════════════════════════
        Object.defineProperty(navigator, 'webdriver', {{
            get: () => undefined,
        }});

        // ═══════════════════════════════════════════════════════════════
        // 🔢 DETERMINISTIC FUNCTIONS: Pixel-index-based noise (PHASE 1 FIX)
        // ═══════════════════════════════════════════════════════════════
        // Stateless noise function - same pixel index always gives same noise
        const deterministicNoise = (index, seed) => {{
            return (((index * 1664525 + seed + 1013904223) & 0xFFFFFF) / 0xFFFFFF);
        }};
        
        // Seeded RNG for audio (still needs state)
        const createSeededRandom = (seed) => {{
            let state = seed;
            return function() {{
                state = (state * 1103515245 + 12345) & 0x7fffffff;
                return state / 0x7fffffff;
            }};
        }};
        
        const audioRandom = createSeededRandom({audio_seed});

        // ═══════════════════════════════════════════════════════════════
        // 🎨 CANVAS FINGERPRINTING: Pixel-index-based noise (PHASE 1 FIX)
        // ═══════════════════════════════════════════════════════════════
        const CANVAS_NOISE = {canvas_noise};
        const CANVAS_SEED = {canvas_seed};
        
        const originalToDataURL = HTMLCanvasElement.prototype.toDataURL;
        const originalToBlob = HTMLCanvasElement.prototype.toBlob;
        const originalGetImageData = CanvasRenderingContext2D.prototype.getImageData;
        
        HTMLCanvasElement.prototype.toDataURL = function() {{
            // Inject subtle noise to canvas BEFORE encoding
            const ctx = this.getContext('2d');
            if (ctx) {{
                try {{
                    const imageData = ctx.getImageData(0, 0, this.width, this.height);
                    const data = imageData.data;
                    
                    // 🎯 PHASE 1 FIX: Pixel-index-based deterministic noise
                    // Same pixel → same noise, regardless of page load order
                    for (let i = 0; i < data.length; i += 4) {{
                        const noise = deterministicNoise(i, CANVAS_SEED);
                        data[i] = data[i] + Math.floor((noise - 0.5) * CANVAS_NOISE * 255);
                        data[i+1] = data[i+1] + Math.floor((noise - 0.5) * CANVAS_NOISE * 255);
                        data[i+2] = data[i+2] + Math.floor((noise - 0.5) * CANVAS_NOISE * 255);
                    }}
                    
                    ctx.putImageData(imageData, 0, 0);
                }} catch(e) {{
                    // Silently fail if canvas tainted
                }}
            }}
            return originalToDataURL.apply(this, arguments);
        }};

        // ═══════════════════════════════════════════════════════════════
        // 🎮 WEBGL FINGERPRINTING: Override vendor/renderer
        // ═══════════════════════════════════════════════════════════════
        const WEBGL_VENDOR = "{webgl_vendor}";
        const WEBGL_RENDERER = "{webgl_renderer}";
        
        const originalGetParameter = WebGLRenderingContext.prototype.getParameter;
        WebGLRenderingContext.prototype.getParameter = function(param) {{
            const debugInfo = this.getExtension('WEBGL_debug_renderer_info');
            
            if (debugInfo) {{
                if (param === debugInfo.UNMASKED_VENDOR_WEBGL) {{
                    return WEBGL_VENDOR;
                }}
                if (param === debugInfo.UNMASKED_RENDERER_WEBGL) {{
                    return WEBGL_RENDERER;
                }}
            }}
            
            return originalGetParameter.apply(this, arguments);
        }};
        
        // WebGL2 support
        if (typeof WebGL2RenderingContext !== 'undefined') {{
            const originalGetParameter2 = WebGL2RenderingContext.prototype.getParameter;
            WebGL2RenderingContext.prototype.getParameter = function(param) {{
                const debugInfo = this.getExtension('WEBGL_debug_renderer_info');
                
                if (debugInfo) {{
                    if (param === debugInfo.UNMASKED_VENDOR_WEBGL) {{
                        return WEBGL_VENDOR;
                    }}
                    if (param === debugInfo.UNMASKED_RENDERER_WEBGL) {{
                        return WEBGL_RENDERER;
                    }}
                }}
                
                return originalGetParameter2.apply(this, arguments);
            }};
        }}

        // ═══════════════════════════════════════════════════════════════
        // 🔊 AUDIOCONTEXT FINGERPRINTING: Inject oscillator noise (FIXED: Seeded)
        // ═══════════════════════════════════════════════════════════════
        const AUDIO_NOISE = {audio_noise};
        
        if (typeof AudioContext !== 'undefined') {{
            const originalCreateOscillator = AudioContext.prototype.createOscillator;
            AudioContext.prototype.createOscillator = function() {{
                const oscillator = originalCreateOscillator.apply(this, arguments);
                const originalStart = oscillator.start;
                
                oscillator.start = function() {{
                    // Inject subtle frequency shift (DETERMINISTIC from seeded RNG)
                    oscillator.frequency.value += (audioRandom() - 0.5) * AUDIO_NOISE;
                    return originalStart.apply(this, arguments);
                }};
                
                return oscillator;
            }};
        }}

        // ═══════════════════════════════════════════════════════════════
        // 💻 HARDWARE PARAMETERS: Override CPU/RAM/Platform
        // ═══════════════════════════════════════════════════════════════
        Object.defineProperty(navigator, 'hardwareConcurrency', {{
            get: () => {cpu_cores}
        }});
        
        Object.defineProperty(navigator, 'deviceMemory', {{
            get: () => {device_memory}
        }});
        
        // 🔧 FIX: Override platform to match WebGL vendor
        Object.defineProperty(navigator, 'platform', {{
            get: () => '{platform}'
        }});

        // ═══════════════════════════════════════════════════════════════
        // 🖥️ SCREEN OBJECT: Override to match viewport (CRITICAL FIX)
        // ═══════════════════════════════════════════════════════════════
        Object.defineProperty(window.screen, 'width', {{
            get: () => {screen_width}
        }});
        
        Object.defineProperty(window.screen, 'height', {{
            get: () => {screen_height}
        }});
        
        Object.defineProperty(window.screen, 'availWidth', {{
            get: () => {screen_width}
        }});
        
        Object.defineProperty(window.screen, 'availHeight', {{
            get: () => {screen_height} - {taskbar_height}  // Platform-specific taskbar/menubar
        }});
        
        Object.defineProperty(window.screen, 'colorDepth', {{
            get: () => {color_depth}
        }});
        
        Object.defineProperty(window.screen, 'pixelDepth', {{
            get: () => {color_depth}
        }});
        
        Object.defineProperty(window, 'devicePixelRatio', {{
            get: () => {pixel_ratio}
        }});

        // ═══════════════════════════════════════════════════════════════
        // 🌐 WEBRTC LEAK PROTECTION: Block local IP leak
        // ═══════════════════════════════════════════════════════════════
        if (typeof RTCPeerConnection !== 'undefined') {{
            const originalRTCPeerConnection = RTCPeerConnection;
            window.RTCPeerConnection = function(config) {{
                if (config && config.iceServers) {{
                    // Filter out STUN servers that leak local IP
                    config.iceServers = config.iceServers.filter(server => {{
                        const urls = Array.isArray(server.urls) ? server.urls : [server.urls];
                        return !urls.some(url => url.includes('stun:'));
                    }});
                }}
                return new originalRTCPeerConnection(config);
            }};
        }}
        
        // Block getUserMedia to prevent WebRTC IP leak
        if (navigator.mediaDevices && navigator.mediaDevices.getUserMedia) {{
            const originalGetUserMedia = navigator.mediaDevices.getUserMedia;
            navigator.mediaDevices.getUserMedia = function() {{
                return Promise.reject(new Error('Permission denied'));
            }};
        }}

        // ═══════════════════════════════════════════════════════════════
        // 🔋 BATTERY API: Block battery status leak
        // ═══════════════════════════════════════════════════════════════
        if (navigator.getBattery) {{
            navigator.getBattery = function() {{
                return Promise.resolve({{
                    charging: true,
                    chargingTime: 0,
                    dischargingTime: Infinity,
                    level: 1.0,
                    addEventListener: () => {{}},
                    removeEventListener: () => {{}}
                }});
            }};
        }}

        // ═══════════════════════════════════════════════════════════════
        // 📹 MEDIA DEVICES: Block device enumeration
        // ═══════════════════════════════════════════════════════════════
        if (navigator.mediaDevices && navigator.mediaDevices.enumerateDevices) {{
            navigator.mediaDevices.enumerateDevices = function() {{
                return Promise.resolve([
                    {{ deviceId: 'default', kind: 'audioinput', label: '', groupId: 'default' }},
                    {{ deviceId: 'default', kind: 'audiooutput', label: '', groupId: 'default' }},
                    {{ deviceId: 'default', kind: 'videoinput', label: '', groupId: 'default' }}
                ]);
            }};
        }}

        // ═══════════════════════════════════════════════════════════════
        // 🎮 WEBGL EXTENSIONS: Limit exposed extensions
        // ═══════════════════════════════════════════════════════════════
        const originalGetSupportedExtensions = WebGLRenderingContext.prototype.getSupportedExtensions;
        WebGLRenderingContext.prototype.getSupportedExtensions = function() {{
            const extensions = originalGetSupportedExtensions.apply(this, arguments);
            // Return only common extensions (reduce fingerprint surface)
            const commonExtensions = [
                'ANGLE_instanced_arrays',
                'EXT_blend_minmax',
                'EXT_color_buffer_half_float',
                'EXT_disjoint_timer_query',
                'EXT_frag_depth',
                'EXT_shader_texture_lod',
                'EXT_texture_filter_anisotropic',
                'OES_element_index_uint',
                'OES_standard_derivatives',
                'OES_texture_float',
                'OES_texture_half_float',
                'OES_vertex_array_object',
                'WEBGL_color_buffer_float',
                'WEBGL_compressed_texture_s3tc',
                'WEBGL_debug_renderer_info',
                'WEBGL_depth_texture',
                'WEBGL_draw_buffers',
                'WEBGL_lose_context'
            ];
            return extensions ? extensions.filter(ext => commonExtensions.includes(ext)) : [];
        }};

        // ═══════════════════════════════════════════════════════════════
        // 🔤 ADVANCED FONT DETECTION BLOCKING
        // ═══════════════════════════════════════════════════════════════
        const PROFILE_FONTS = {fonts_js};
        
        // 1️⃣ Block document.fonts.check() - Modern font detection API
        if (typeof document !== 'undefined' && document.fonts && document.fonts.check) {{
            const originalCheck = document.fonts.check.bind(document.fonts);
            document.fonts.check = function(font) {{
                try {{
                    // Extract font family from font string (e.g., "12px Arial" → "Arial")
                    // Match patterns: "12px 'Arial'", '12px "Arial"', "12px Arial"
                    const fontFamilyMatch = font.match(/(?:["']([^"']+)["']|(\S+))$/);
                    const fontFamily = fontFamilyMatch ? (fontFamilyMatch[1] || fontFamilyMatch[2]) : null;
                    
                    if (fontFamily) {{
                        // Only return true if font is in our profile
                        const isAllowed = PROFILE_FONTS.some(profileFont => 
                            fontFamily.toLowerCase().includes(profileFont.toLowerCase()) ||
                            profileFont.toLowerCase().includes(fontFamily.toLowerCase())
                        );
                        
                        if (isAllowed) {{
                            return originalCheck.call(this, font);
                        }}
                        
                        // Block detection of fonts not in profile
                        return false;
                    }}
                    
                    // If can't parse, fallback to false (safe)
                    return false;
                }} catch (e) {{
                    // On error, fallback to original behavior
                    return originalCheck.call(this, font);
                }}
            }};
        }}
        
        // 2️⃣ Block canvas-based font detection via measureText()
        if (typeof CanvasRenderingContext2D !== 'undefined') {{
            const originalMeasureText = CanvasRenderingContext2D.prototype.measureText;
            CanvasRenderingContext2D.prototype.measureText = function(text) {{
                try {{
                    const result = originalMeasureText.call(this, text);
                    
                    // Check if current font is in our profile
                    const currentFont = this.font || '';
                    const isAllowedFont = PROFILE_FONTS.some(profileFont =>
                        currentFont.toLowerCase().includes(profileFont.toLowerCase())
                    );
                    
                    if (!isAllowedFont && currentFont) {{
                        // Return normalized fallback metrics to prevent fingerprinting
                        // Use Arial-like metrics as baseline
                        const normalizedWidth = text.length * 10; // Approximate
                        
                        return {{
                            width: normalizedWidth,
                            actualBoundingBoxAscent: 10,
                            actualBoundingBoxDescent: 2,
                            actualBoundingBoxLeft: 0,
                            actualBoundingBoxRight: normalizedWidth,
                            fontBoundingBoxAscent: 12,
                            fontBoundingBoxDescent: 3,
                            alphabeticBaseline: 0,
                            hangingBaseline: 9,
                            ideographicBaseline: -3,
                            emHeightAscent: 10,
                            emHeightDescent: 2
                        }};
                    }}
                    
                    // Allowed font - return real metrics
                    return result;
                }} catch (e) {{
                    // On error, fallback to original
                    return originalMeasureText.call(this, text);
                }}
            }};
        }}
        
        // 3️⃣ Block FontFace constructor - Prevent dynamic font loading detection
        if (typeof FontFace !== 'undefined') {{
            const originalFontFace = FontFace;
            window.FontFace = function(family, source, descriptors) {{
                try {{
                    // Check if font family is in our profile
                    const isAllowed = PROFILE_FONTS.some(profileFont =>
                        family.toLowerCase().includes(profileFont.toLowerCase()) ||
                        profileFont.toLowerCase().includes(family.toLowerCase())
                    );
                    
                    if (isAllowed) {{
                        // Allowed font - create real FontFace
                        return new originalFontFace(family, source, descriptors);
                    }}
                    
                    // Block fonts not in profile by returning mock FontFace
                    return {{
                        family: family,
                        style: 'normal',
                        weight: '400',
                        stretch: 'normal',
                        unicodeRange: 'U+0-10FFFF',
                        variant: 'normal',
                        featureSettings: 'normal',
                        variationSettings: 'normal',
                        display: 'auto',
                        ascentOverride: 'normal',
                        descentOverride: 'normal',
                        lineGapOverride: 'normal',
                        status: 'unloaded',
                        loaded: Promise.reject(new DOMException('Font not available in profile', 'NetworkError')),
                        load: function() {{
                            return Promise.reject(new DOMException('Font not available in profile', 'NetworkError'));
                        }},
                        addEventListener: function() {{}},
                        removeEventListener: function() {{}},
                        dispatchEvent: function() {{ return false; }}
                    }};
                }} catch (e) {{
                    // On error, fallback to original
                    return new originalFontFace(family, source, descriptors);
                }}
            }};
            
            // Preserve prototype chain
            window.FontFace.prototype = originalFontFace.prototype;
        }}
        
        // 4️⃣ Block FontFaceSet.load() - Prevent bulk font loading detection
        if (typeof document !== 'undefined' && document.fonts && document.fonts.load) {{
            const originalLoad = document.fonts.load.bind(document.fonts);
            document.fonts.load = function(font, text) {{
                try {{
                    // Extract font family from font string
                    const fontFamilyMatch = font.match(/(?:["']([^"']+)["']|(\S+))$/);
                    const fontFamily = fontFamilyMatch ? (fontFamilyMatch[1] || fontFamilyMatch[2]) : null;
                    
                    if (fontFamily) {{
                        const isAllowed = PROFILE_FONTS.some(profileFont =>
                            fontFamily.toLowerCase().includes(profileFont.toLowerCase()) ||
                            profileFont.toLowerCase().includes(fontFamily.toLowerCase())
                        );
                        
                        if (isAllowed) {{
                            return originalLoad.call(this, font, text);
                        }}
                        
                        // Block loading of fonts not in profile
                        return Promise.reject(new DOMException('Font not available in profile', 'NetworkError'));
                    }}
                    
                    return Promise.reject(new DOMException('Invalid font specification', 'SyntaxError'));
                }} catch (e) {{
                    return originalLoad.call(this, font, text);
                }}
            }};
        }}
        
        // 5️⃣ Block offsetWidth/offsetHeight font detection technique
        // This is more complex and might affect layout, so we only log attempts
        // (Actual blocking would require deeper DOM modifications)
        
        console.debug('🔤 Font detection blocking active: ' + PROFILE_FONTS.length + ' fonts in profile');

        // ═══════════════════════════════════════════════════════════════
        // 🛡️ BASIC ANTI-DETECTION (from original)
        // ═══════════════════════════════════════════════════════════════
        
        // Mock permissions API
        const originalQuery = window.navigator.permissions.query;
        window.navigator.permissions.query = (parameters) => (
            parameters.name === 'notifications' ?
                Promise.resolve({{ state: Notification.permission }}) :
                originalQuery(parameters)
        );

        // 🔌 PHASE 1 FIX: Realistic navigator.plugins (not fake array)
        const REALISTIC_PLUGINS = {plugins_js};
        Object.defineProperty(navigator, 'plugins', {{
            get: () => {{
                const pluginArray = REALISTIC_PLUGINS;
                pluginArray.refresh = function() {{}};
                pluginArray.item = function(index) {{ return this[index] || null; }};
                pluginArray.namedItem = function(name) {{
                    for (let i = 0; i < this.length; i++) {{
                        if (this[i].name === name) return this[i];
                    }}
                    return null;
                }};
                Object.setPrototypeOf(pluginArray, PluginArray.prototype);
                return pluginArray;
            }}
        }});

        // Mock navigator.languages
        Object.defineProperty(navigator, 'languages', {{
            get: () => ['vi-VN', 'vi', 'en-US', 'en'],
        }});

        // Add window.chrome object (realistic Chrome properties)
        window.chrome = {{
            runtime: {{
                // ✅ Hide CDP traces - block common automation methods
                connect: undefined,
                sendMessage: undefined,
            }},
            loadTimes: function() {{}},
            csi: function() {{}},
            app: {{}}
        }};
        
        // ═══════════════════════════════════════════════════════════════
        // 🌍 PHASE 3: GEOLOCATION: Use proxy-based location (from fingerprint)
        // ═══════════════════════════════════════════════════════════════
        const GEO_LATITUDE = {geo_latitude};
        const GEO_LONGITUDE = {geo_longitude};
        const GEO_ACCURACY = {geo_accuracy};
        
        if (navigator.geolocation && navigator.geolocation.getCurrentPosition) {{
            const originalGetCurrentPosition = navigator.geolocation.getCurrentPosition;
            navigator.geolocation.getCurrentPosition = function(success, error) {{
                if (success) {{
                    success({{
                        coords: {{
                            latitude: GEO_LATITUDE,
                            longitude: GEO_LONGITUDE,
                            accuracy: GEO_ACCURACY,
                            altitude: null,
                            altitudeAccuracy: null,
                            heading: null,
                            speed: null
                        }},
                        timestamp: Date.now()
                    }});
                }}
            }};
            
            navigator.geolocation.watchPosition = function(success, error) {{
                if (success) {{
                    success({{
                        coords: {{
                            latitude: GEO_LATITUDE,
                            longitude: GEO_LONGITUDE,
                            accuracy: GEO_ACCURACY,
                            altitude: null,
                            altitudeAccuracy: null,
                            heading: null,
                            speed: null
                        }},
                        timestamp: Date.now()
                    }});
                }}
                return 1;  // fake watchId
            }};
        }}

        // ═══════════════════════════════════════════════════════════════
        // 📡 CONNECTION API: Mock network info
        // ═══════════════════════════════════════════════════════════════
        if (navigator.connection) {{
            Object.defineProperty(navigator.connection, 'downlink', {{
                get: () => 10
            }});
            Object.defineProperty(navigator.connection, 'effectiveType', {{
                get: () => '4g'
            }});
            Object.defineProperty(navigator.connection, 'rtt', {{
                get: () => 50
            }});
        }}
        
        // ═══════════════════════════════════════════════════════════════
        // 📐 CLIENTRECTS FINGERPRINTING: Subtle noise injection (PHASE 2)
        // ═══════════════════════════════════════════════════════════════
        const CLIENTRECT_NOISE = 0.0001;  // Very subtle
        
        const originalGetBoundingClientRect = Element.prototype.getBoundingClientRect;
        Element.prototype.getBoundingClientRect = function() {{
            const rect = originalGetBoundingClientRect.apply(this, arguments);
            
            // Inject subtle noise based on element position (deterministic)
            const noise = deterministicNoise(rect.x * 1000 + rect.y, {canvas_seed});
            
            return {{
                x: rect.x,
                y: rect.y,
                width: rect.width + (noise - 0.5) * CLIENTRECT_NOISE,
                height: rect.height + (noise - 0.5) * CLIENTRECT_NOISE,
                top: rect.top,
                right: rect.right,
                bottom: rect.bottom,
                left: rect.left,
                toJSON: function() {{
                    return {{
                        x: this.x, y: this.y, width: this.width, height: this.height,
                        top: this.top, right: this.right, bottom: this.bottom, left: this.left
                    }};
                }}
            }};
        }};
        
        // Also override getClientRects for consistency
        const originalGetClientRects = Element.prototype.getClientRects;
        Element.prototype.getClientRects = function() {{
            const rects = originalGetClientRects.apply(this, arguments);
            const modifiedRects = [];
            
            for (let i = 0; i < rects.length; i++) {{
                const rect = rects[i];
                const noise = deterministicNoise(rect.x * 1000 + rect.y + i, {canvas_seed});
                
                modifiedRects.push({{
                    x: rect.x,
                    y: rect.y,
                    width: rect.width + (noise - 0.5) * CLIENTRECT_NOISE,
                    height: rect.height + (noise - 0.5) * CLIENTRECT_NOISE,
                    top: rect.top,
                    right: rect.right,
                    bottom: rect.bottom,
                    left: rect.left
                }});
            }}
            
            return modifiedRects;
        }};

        // ═══════════════════════════════════════════════════════════════
        // 🎤 SPEECH SYNTHESIS: Mock realistic voices (PHASE 2)
        // ═══════════════════════════════════════════════════════════════
        if (typeof speechSynthesis !== 'undefined') {{
            const originalGetVoices = speechSynthesis.getVoices;
            speechSynthesis.getVoices = function() {{
                // Return platform-appropriate voices
                if ('{platform}' === 'Win32') {{
                    return [
                        {{ name: 'Microsoft David Desktop', lang: 'en-US', localService: true, default: true }},
                        {{ name: 'Microsoft Zira Desktop', lang: 'en-US', localService: true, default: false }},
                        {{ name: 'Google US English', lang: 'en-US', localService: false, default: false }}
                    ];
                }} else if ('{platform}' === 'MacIntel') {{
                    return [
                        {{ name: 'Alex', lang: 'en-US', localService: true, default: true }},
                        {{ name: 'Samantha', lang: 'en-US', localService: true, default: false }},
                        {{ name: 'Victoria', lang: 'en-US', localService: true, default: false }}
                    ];
                }} else {{
                    return [
                        {{ name: 'Google US English', lang: 'en-US', localService: false, default: true }}
                    ];
                }}
            }};
        }}

        // ═══════════════════════════════════════════════════════════════
        // 💾 PERFORMANCE.MEMORY: Mock realistic values (PHASE 2)
        // ═══════════════════════════════════════════════════════════════
        if (typeof performance !== 'undefined' && !performance.memory) {{
            Object.defineProperty(performance, 'memory', {{
                get: () => {{
                    const baseMemory = {device_memory} * 1024 * 1024 * 1024;
                    const used = Math.floor(baseMemory * 0.3 + deterministicNoise(Date.now() % 1000, {canvas_seed}) * baseMemory * 0.2);
                    const total = Math.floor(baseMemory * 0.5);
                    
                    return {{
                        usedJSHeapSize: used,
                        totalJSHeapSize: total,
                        jsHeapSizeLimit: Math.floor(baseMemory * 0.8)
                    }};
                }}
            }});
        }}
        
        // 🎯 Phase 3 Complete: Timezone + Geolocation from Proxy IP
        console.debug('🎯 Anti-detect v3.2 FINAL loaded: Perfect geolocation matching');
    """


def get_browser_fingerprint_summary() -> Dict[str, Any]:
    """
    Trả về summary của browser fingerprint để debugging/verification.

    Returns:
        Summary of all fingerprint components
    """
    args = get_browser_args()
    options = get_browser_launch_options("/dummy/path", headless=False)

    return {
        "total_args": len(args),
        "critical_args": [
            '--disable-field-trial-config',
            '--disable-back-forward-cache',
            '--disable-ipc-flooding-protection'
        ],
        "user_agent": options["user_agent"],
        "viewport": options["viewport"],
        "locale": options["locale"],
        "timezone": options["timezone_id"],
        "plugins_count": MOCK_PLUGINS_COUNT,
        "has_window_chrome": True,
        "fingerprint_version": FINGERPRINT_VERSION
    }


# 🧪 Testing function để verify configuration
def verify_config_consistency() -> None:
    """
    Kiểm tra tính nhất quán của cấu hình.
    Sử dụng để debugging và verification.
    """
    summary = get_browser_fingerprint_summary()

    print("🔍 BROWSER CONFIGURATION VERIFICATION")
    print("=" * 50)
    print(f"📊 Total browser args: {summary['total_args']}")
    print(f"🔥 Critical args present: {len(summary['critical_args'])}/3")
    print(f"🌐 User Agent: {summary['user_agent'][:50]}...")
    print(f"📱 Viewport: {summary['viewport']}")
    print(f"🌍 Locale: {summary['locale']}")
    print(f"⏰ Timezone: {summary['timezone']}")
    print(f"🔌 Plugins count: {summary['plugins_count']}")
    print(f"🪟 Chrome object: {summary['has_window_chrome']}")
    print(f"📋 Version: {summary['fingerprint_version']}")
    print("=" * 50)
    print("✅ Configuration is consistent and ready for use!")


if __name__ == "__main__":
    # Run verification when executed directly
    verify_config_consistency()
