from django import forms

class WorkbookUploadForm(forms.Form):
    workbook = forms.FileField(widget=forms.ClearableFileInput(attrs={"class": "form-control", "accept": ".xlsx"}))

    def clean_workbook(self):
        file = self.cleaned_data["workbook"]
        if not file.name.lower().endswith(".xlsx"):
            raise forms.ValidationError("Please upload an Excel .xlsx workbook.")
        return file

class ForecastForm(forms.Form):
    warehouse = forms.ChoiceField(label="Sales location")
    sku = forms.ChoiceField(label="Product SKU")
