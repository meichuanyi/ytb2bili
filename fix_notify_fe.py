from pathlib import Path
p = Path("/root/projects/ytb2bili-main/web/src/app/dashboard/settings/page.tsx")
s = p.read_text(encoding="utf8")

# fix Bell import
s = s.replace(
    """import {
  LogOut,
  KeyRound,
  ChevronDown,
  Check,
  Languages,
  AudioLines,
  SlidersHorizontal,
  UploadCloud,
  LayoutTemplate,
} from 'lucide-react';""",
    """import {
  Bell,
  LogOut,
  KeyRound,
  ChevronDown,
  Check,
  Languages,
  AudioLines,
  SlidersHorizontal,
  UploadCloud,
  LayoutTemplate,
} from 'lucide-react';""",
)

# remove accidental Bell from wrong import if any
s = s.replace("import { Bell, useCallback, useEffect, useState } from 'react';",
              "import { useCallback, useEffect, useState } from 'react';")
s = s.replace("import { Bell,\n", "import {\n")

# fix test endpoint path
s = s.replace("fetch('/api/v1/system/notify/test'", "fetch('/api/v1/system/settings/notify/test'")

p.write_text(s, encoding="utf8")
print("Bell in lucide:", "Bell,\n  LogOut," in s)
print("test path fixed:", "system/settings/notify/test" in s)
print("react import:", [line for line in s.splitlines() if "from 'react'" in line][:3])
