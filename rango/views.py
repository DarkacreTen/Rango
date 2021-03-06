from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required

# datetime object is within datetime module
from datetime import datetime

from django.http import HttpResponse
from .models import Category, Page, UserProfile
from .forms import CategoryForm, PageForm, UserForm, UserProfileForm

# import search function
from rango.bing_search import run_query

# Create your views here.

# Encodes and decodes URL
def encode_url(category_name, encode):
    # if encode is true then replace with underscores
    if encode:
        name = category_name.replace(' ', '_')

    # otherwise replace underscore with space
    else:
        name = category_name.replace('_', ' ')

    return name

# if no arguments specified, default values will be used
# gets full category list and encodes the url name for them
def get_category_list(max_results=0, starts_with=''):
    cat_list = []
    if starts_with:
        cat_list = Category.objects.filter(name__startswith=starts_with)
    else:
        cat_list = Category.objects.all()

    if max_results > 0:
        if len(cat_list) > max_results:
            cat_list = cat_list[:max_results]

    for cat in cat_list:
        cat.url = encode_url(cat.name, True)

    return cat_list

def suggest_category(request):
    cat_list = []
    starts_with = ''

    # set max results to 8
    max_results = 8

    if request.method == 'GET':
        # 'suggestion' passed through rango-ajax $.get request
        # routed by way of: rango-ajax get request -> urls -> suggest_category
        starts_with = request.GET['suggestion']

    # Still unclear what this function does
    else:
        starts_with = request.POST['suggestion']

    cat_list = get_category_list(max_results, starts_with)

    return render(request, 'rango/category_list.html', {'cat_list':cat_list})

def index(request):

    category_list = get_category_list()
    context_dict = {'cat_list': category_list}

    #most viewed pages; only returns top 5
    most_viewed = Page.objects.order_by('-views')[:5]
    context_dict['pages'] = most_viewed

    # .url can be added to model even if not explicitly defined in model (like pk?)
    for category in category_list:
        category.url = encode_url(category.name, True)


    # can check for cookies in request.session object
    # if the key doesn't exist, will return None, which will fail the test
    if request.session.get('last_visit'):
        last_visit_time = request.session.get('last_visit')
        visits = request.session.get('visits', 0)

        # assumes increment when visits occur daily
        if (datetime.now() - datetime.strptime(last_visit_time[:-7],
            "%Y-%m-%d %H:%M:%S")).days > 0:
            #...increment visits by 1
            request.session['visits'] = visits + 1
            #...reset last_visit to now
            request.session['last_visit'] = str(datetime.now())
        else:
            request.session['last_visit'] = str(datetime.now())
            # default visits to 1 now that they have visited
            request.session['visits'] = 1

    # render returns an HttpResponse object
    return render(request, 'rango/index.html', context_dict)

def about(request):
    # shows how many times has visited previously
    # e.g. if visits session variable exists, then have visited before

    if request.session.get('visits'):
        count = request.session.get('visits')
    else:
        count = 0

    return render(request, 'rango/about.html', {'visits': count, 'cat_list': get_category_list()})

def category(request, category_name_url):
    # replace underscores with spaces. Assumes url uses underscores
    category_name = encode_url(category_name_url, False)
    category_list = get_category_list()
    context_dict = {'category_name': category_name,
        'category_name_url': category_name_url,
        'cat_list': category_list}

    # May want to use get_object_or_404, but don't want page to throw exception

    try:
        category = Category.objects.get(name=category_name)

        # Find all associated pages
        pages = Page.objects.filter(category=category)

        # Add category and pages to context_dict pass to urls.py and templates
        context_dict['pages'] = pages
        context_dict['category'] = category

    except Category.DoesNotExist:
        #Don't do anything
        pass

    result_list = search(request)
    context_dict['result_list'] = result_list

    # can pass through anything back tot he templates in a dict format
    return render(request, 'rango/category.html', context_dict)

def track_url(request):

    # page_id is passed from category.html as ?page_id ={{ page.id }}
    # where ? allows for an ending so that can input key, value pairs
    if 'page_id' in request.GET:
        page_id = request.GET.get('page_id')
        try:
            # all objects have both id and pk.  Id is faster
            page = Page.objects.get(id=page_id)
            page.views += 1
            page.save()
            url = page.url
        except:
            pass

    return redirect(url)

@login_required
def add_category(request):
    if request.method == "POST":
        form = CategoryForm(request.POST)

        if form.is_valid():
            form.save(commit=True)
            return index(request)
        else:
            print(form.errors)
    else:
        form = CategoryForm()

    return render(request, 'rango/add_category.html', {'form': form, 'cat_list': get_category_list()})

@login_required
def like_category(request):
    cat_id = None
    if request.method == 'GET':
        # 'category_id' must be passed through GET or POST in category.html or
        # from ajax request in rango-ajax.js
        cat_id = request.GET['category_id']

    likes = 0
    if cat_id:
        category = Category.objects.get(id=int(cat_id))
        if category:
            likes = category.likes + 1
            category.likes = likes
            category.save()

    return HttpResponse(likes)

@login_required
def add_page(request, category_name_url):
    # category_name_url will be passed in from the add_page.html view with request
    category_name = encode_url(category_name_url, False)

    if request.method == "POST":
        form = PageForm(request.POST)

        if form.is_valid():
            # Like blog, do not commit until fields are populated
            page = form.save(commit=False)

            #retrieve category since it is hidden
            cat = Category.objects.get(name=category_name)
            page.category = cat

            # Default value for # of views in new page
            page.views = 0

            # Save after hidden values added
            page.save()

            #return category view now that it's saved
            return category(request, category_name_url)
        else:
            print(form.errors)
    else:
        form = PageForm()

    return render(request, 'rango/add_page.html', {'category_name_url': category_name_url,
        'category_name': category_name, 'form': form, 'cat_list': get_category_list()})

@login_required
def auto_add_page(request):
    cat_id = None
    title = None
    url = None
    context_dict = {}

    if request.method == 'GET':
        cat_id = request.GET['category_id']
        title = request.GET['title']
        url = request.GET['url']
        print(cat_id, title, url)

        if cat_id:
            category = Category.objects.get(id=int(cat_id))

            # get_or_create is a shortcut that will call save automatically if
            # Page.DoesNotExist returns True
            p = Page.objects.get_or_create(category=category, title=title, url=url)

            pages = Page.objects.filter(category=category).order_by('-views')

            # Passes pages to page_list.html
            context_dict['pages'] = pages

    # will overwrite the div marked div-display
    return render(request, 'rango/page_list.html', context_dict)

def register(request):

    #is registration successful; set to False initially
    registered = False

    if request.method == "POST":
        #get info from form for both UserForm and UserProfileForm
        user_form = UserForm(data=request.POST)
        profile_form = UserProfileForm(data=request.POST)

        if user_form.is_valid() and profile_form.is_valid():
            user = user_form.save()

            # .set_password hashes the password before updating the user object
            user.set_password(user.password)
            user.save()

            # set commit to false initially so that we can sort out user attribute here first
            # Need to save data from profile_form before it can be accessed
            profile = profile_form.save(commit=False)

            #sets the userprofile equal to the saved user
            profile.user = user

            # 'picture' is the var name we declared in UserProfile,
            # but checks if it's in the request; upload if True

            if 'picture' in request.FILES:
                profile.picture = request.FILES['picture']

            profile.save()

            # registration is now complete
            registered = True
        #invalid forms or something else?
        else:
            print(user_form.errors, profile_form.errors)
    # if not POST request, then render blank forms as usual
    else:
        user_form = UserForm()
        profile_form = UserProfileForm()

    return render(request, 'rango/register.html', {
        'user_form': user_form, 'profile_form': profile_form, 'registered': registered, 'cat_list':get_category_list(),
        })

def user_login(request):
    if request.method == "POST":
        username = request.POST['username']
        password = request.POST['password']

        #Django's internal authentication; returns None if not registered
        user = authenticate(username=username, password=password)

        if user is not None:
            #check if account is active (in admin)
            if user.is_active:
                #login and redirect to homepage
                login(request, user)
                return redirect('rango:index')
            else:
                return HttpResponse("Your account is disabled")
        else:
            #for bad login details
            print("Invalid login details: {0}, {1}".format(username, password))
            return HttpResponse("Invalid login details supplied.")

    # if it's not a POST, it's probably a GET so pass back the form
    else:
        return render(request, 'rango/login.html', {'cat_list': get_category_list()})

@login_required
def restricted(request):
    return HttpResponse("You have already logged in")

# should only access view if logged in
@login_required
def user_logout(request):
    logout(request)
    #redirect to homepage
    return redirect('rango:index')

# Show profile
@login_required
def profile(request):
    cat_list = get_category_list()
    context_dict = {'cat_list': cat_list}

    # get can look for individual keys, request handles user
    u = User.objects.get(username=request.user)

    try:
        up = UserProfile.objects.get(user=u)
    except:
        up = None

    context_dict['user']= u
    context_dict['userprofile'] = up
    return render(request, 'rango/profile.html', context_dict)

# Category view now calls search
def search(request):
    result_list = []
    if request.method == 'POST':
        #passed in through form name = "query"
        query = request.POST['query'].strip()

        if query:
            #run bing function
            result_list = run_query(query)

    return result_list
