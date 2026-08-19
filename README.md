# ZoOz Online — نظام الشهادات

نسخة أونلاين من تطبيق مؤسسة الفهد للخدمات الجمركية والملاحية، ببيانات على Google Sheets وبدخول بالصلاحيات.

## ملفات المشروع

| ملف | الوصف |
|---|---|
| `app.py` | التطبيق الرئيسي |
| `requirements.txt` | الحزم المطلوبة |
| `back22.jpg` / `back33.jpg` | الخلفيات |
| `.streamlit/secrets.toml` | الأسرار (الأسيت + المستخدمون) |
| `.streamlit/config.toml` | إعدادات المظهر |

## الإعدادات

البيانات في Google Sheets، والتحكم بالنظام عبر `secrets.toml`:

- `google_sheet_id` — رقم الجوجل شيت
- `[gcp_service_account]` — مفتاح خدمة جوجل (Service Account) الذي يجب منحه صلاحية **Editor** على الشيت
- `[users.*]` — المستخدمون والصلاحيات

### صلاحيات المستخدم

| الحقل | الوصف |
|---|---|
| `password` | كلمة المرور |
| `role = "main"` | أدمن — صلاحيات كاملة (كل الشركات، تعديل، حذف) |
| `role = "viewer"` | قراءة فقط |
| `access = "edit"` | اختياري — يسمح بالتعديل والإضافة |
| `companies = [...]` | اختياري — قصر الرؤية على شركات محددة (لو محذوف، يشوف كل الشركات) |

مثال:

```toml
[users."فهد"]
password = "123"
role = "viewer"
access = "edit"
companies = ["ال اس مان", "ادو مينا لصناعه مواد البناء"]
```

ملاحظة: الأسماء العربية في `[users."..."]` يجب أن تكون بين علامتي اقتباس.

## التشغيل محليًا

```bash
pip install -r requirements.txt
streamlit run app.py
```

## النشر على Streamlit Cloud

1. ارفع ملفات المشروع لمستودع GitHub (بدون `.streamlit/secrets.toml` وأي أسرار).
2. من [share.streamlit.io](https://share.streamlit.io) → **New app** → اختر المستودع و `app.py`.
3. من **Settings → Secrets** ضع نفس محتوى `.streamlit/secrets.toml` (الكامل).
4. Deploy.

بعد النشر، البيانات تتحفظ تلقائيًا في Google Sheets — أي تعديل من أي شخص يتزامن للجميع فورًا.