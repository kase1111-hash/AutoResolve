## 🤖 AutoResolve - Fix Rejected

The proposed fix for this issue has been **rejected**.

{% if rejected_by %}
**Rejected by:** @{{ rejected_by }}
{% endif %}

{% if rejection_reason %}
**Reason:** {{ rejection_reason }}
{% endif %}

---

### What happens next?

- This fix proposal has been archived
- The issue remains open for manual resolution
- You can request a new fix by adding the `bug` label or commenting `@autoresolve retry`

{% if security_issues %}
### Security Concerns

The fix was rejected due to the following security issues:

{% for issue in security_issues %}
- **{{ issue.severity }}**: {{ issue.message }} ({{ issue.file }}:{{ issue.line }})
{% endfor %}
{% endif %}

---
<sub>AutoResolve v{{ version }}</sub>
