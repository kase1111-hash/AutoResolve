## 🤖 AutoResolve Analysis Complete

| Check | Status |
|-------|--------|
| **Reproduction** | {{ reproduction_status }} |
| **Fix Generated** | {{ fix_status }} |
| **Security Scan** | {{ security_status }} |

### Proposed Fix

<details>
<summary>Click to view diff ({{ lines_changed }} lines changed)</summary>

```diff
{{ diff }}
```

</details>

### Security Report

{{ security_summary }}

---

### Actions

| Command | Description |
|---------|-------------|
| `@autoresolve approve` | Create PR and merge |
| `@autoresolve approve --no-merge` | Create PR only |
| `@autoresolve reject` | Decline this fix |
| `@autoresolve regenerate` | Generate a new fix |
| 👍 reaction | Same as approve |
| 👎 reaction | Same as reject |

⏱️ **Expires:** {{ expiry_date }} ({{ days_remaining }} days)

---
<sub>AutoResolve v{{ version }} • [Documentation]({{ docs_url }}) • [Report Issue]({{ report_url }})</sub>
