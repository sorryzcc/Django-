from django.shortcuts import render
 
def runoob(request):
    context          = {}
    context['hello'] = 'Hello World111!'
    return render(request, 'runoob.html', context)