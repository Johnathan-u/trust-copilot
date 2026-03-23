# Page snapshot

```yaml
- generic [active] [ref=e1]:
  - alert [ref=e2]: Trust Copilot
  - main [ref=e3]:
    - generic [ref=e4]:
      - generic [ref=e5]:
        - generic [ref=e6]: ✓
        - heading "Trust Copilot" [level=1] [ref=e7]
      - paragraph [ref=e8]: Answer compliance questionnaires with AI and evidence.
      - generic [ref=e9]:
        - generic [ref=e10]:
          - generic [ref=e11]: Email
          - textbox [ref=e12]
        - generic [ref=e13]:
          - generic [ref=e14]: Password
          - textbox [ref=e15]
        - generic [ref=e16] [cursor=pointer]:
          - checkbox "Keep me signed in" [ref=e17]
          - text: Keep me signed in
        - button "Sign in" [ref=e18] [cursor=pointer]
        - generic [ref=e23]: or continue with
        - generic [ref=e24]:
          - link "Sign in with Google" [ref=e25] [cursor=pointer]:
            - /url: /api/auth/oauth/google
            - img [ref=e26]
            - text: Sign in with Google
          - link "Sign in with GitHub" [ref=e31] [cursor=pointer]:
            - /url: /api/auth/oauth/github
            - img [ref=e32]
            - text: Sign in with GitHub
      - paragraph [ref=e34]:
        - link "Create account" [ref=e35] [cursor=pointer]:
          - /url: /register
        - text: ·
        - link "Forgot password?" [ref=e36] [cursor=pointer]:
          - /url: /forgot-password
      - paragraph [ref=e37]: "Demo: demo@trust.local / j (clear and re-enter for other accounts)"
```