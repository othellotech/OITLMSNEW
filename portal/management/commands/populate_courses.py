# portal/management/commands/populate_courses.py

from django.core.management.base import BaseCommand
from django.db import transaction
from django.contrib.auth import get_user_model
from portal.models import Course, Playlist, Lesson

User = get_user_model()

class Command(BaseCommand):
    help = 'Populates the database with 5 courses, playlists, and lessons'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('Starting database population...'))
        
        # Create or get a default instructor
        instructor = self.get_or_create_instructor()
        
        # Define course data
        courses_data = [
            {
                'title': 'Data Analysis',
                'description': 'Master data analysis techniques including statistics, data visualization, and business intelligence. Learn to extract insights from complex datasets.',
                'playlists': [
                    {
                        'title': 'Introduction to Data Analysis',
                        'lessons': [
                            'What is Data Analysis?',
                            'The Data Analysis Process',
                            'Types of Data',
                            'Data Collection Methods',
                            'Data Cleaning Basics',
                            'Introduction to Statistics',
                            'Data Visualization Fundamentals',
                            'Tools for Data Analysis',
                            'Real-world Applications',
                            'Ethics in Data Analysis',
                            'Data Analysis Career Path',
                            'Setting Up Your Environment'
                        ]
                    },
                    {
                        'title': 'Statistical Analysis',
                        'lessons': [
                            'Descriptive Statistics',
                            'Inferential Statistics',
                            'Probability Theory',
                            'Hypothesis Testing',
                            'Regression Analysis',
                            'Correlation Analysis',
                            'ANOVA',
                            'Time Series Analysis',
                            'Statistical Software',
                            'Statistical Modeling',
                            'Data Distributions',
                            'Sampling Methods'
                        ]
                    }
                ]
            },
            {
                'title': 'ICT Fundamentals',
                'description': 'Learn the essential concepts of Information and Communication Technology (ICT) including hardware, software, networking, and digital literacy.',
                'playlists': [
                    {
                        'title': 'ICT Basics',
                        'lessons': [
                            'Introduction to ICT',
                            'Computer Hardware',
                            'Computer Software',
                            'Operating Systems',
                            'File Management',
                            'Networking Basics',
                            'Internet Fundamentals',
                            'Cybersecurity Basics',
                            'Cloud Computing',
                            'Database Concepts',
                            'Digital Communication',
                            'ICT in Business'
                        ]
                    },
                    {
                        'title': 'ICT Applications',
                        'lessons': [
                            'Office Applications',
                            'Digital Collaboration',
                            'IT Support Fundamentals',
                            'Data Management',
                            'E-commerce',
                            'Social Media Technology',
                            'Mobile Technologies',
                            'ICT Project Management',
                            'IT Service Management',
                            'Disaster Recovery',
                            'ICT Ethics',
                            'Future Trends in ICT'
                        ]
                    }
                ]
            },
            {
                'title': 'Web Development',
                'description': 'Complete guide to web development covering HTML, CSS, JavaScript, frontend frameworks, backend development, and modern web technologies.',
                'playlists': [
                    {
                        'title': 'Frontend Web Development',
                        'lessons': [
                            'HTML Fundamentals',
                            'CSS Styling',
                            'JavaScript Basics',
                            'DOM Manipulation',
                            'Responsive Design',
                            'CSS Frameworks',
                            'JavaScript Frameworks',
                            'React.js Introduction',
                            'State Management',
                            'RESTful APIs',
                            'Web Performance',
                            'Web Security Basics'
                        ]
                    },
                    {
                        'title': 'Backend Web Development',
                        'lessons': [
                            'Backend Fundamentals',
                            'Node.js Basics',
                            'Python Web Frameworks',
                            'Database Integration',
                            'API Development',
                            'Authentication & Authorization',
                            'Web Servers & Deployment',
                            'Microservices',
                            'Cloud Deployment',
                            'DevOps Basics',
                            'Testing & Debugging',
                            'Full-stack Integration'
                        ]
                    }
                ]
            },
            {
                'title': 'Python Programming',
                'description': 'Comprehensive Python programming course from basics to advanced concepts, data structures, algorithms, and real-world applications.',
                'playlists': [
                    {
                        'title': 'Python Fundamentals',
                        'lessons': [
                            'Python Introduction',
                            'Variables & Data Types',
                            'Control Flow',
                            'Functions & Modules',
                            'Data Structures',
                            'String Manipulation',
                            'File I/O Operations',
                            'Exception Handling',
                            'Python Standard Library',
                            'Object-Oriented Programming',
                            'Python Development Tools',
                            'Writing Clean Code'
                        ]
                    },
                    {
                        'title': 'Advanced Python',
                        'lessons': [
                            'Advanced OOP',
                            'Decorators & Generators',
                            'Context Managers',
                            'Multithreading',
                            'Asynchronous Programming',
                            'Design Patterns',
                            'Web Scraping',
                            'Data Science Libraries',
                            'Machine Learning Basics',
                            'Testing Python Code',
                            'Python Packaging',
                            'Performance Optimization'
                        ]
                    }
                ]
            },
            {
                'title': 'Artificial Intelligence',
                'description': 'Explore the fundamentals of AI including machine learning, deep learning, natural language processing, and computer vision.',
                'playlists': [
                    {
                        'title': 'AI Foundations',
                        'lessons': [
                            'Introduction to AI',
                            'History of AI',
                            'Machine Learning Basics',
                            'Deep Learning Fundamentals',
                            'Neural Networks',
                            'Natural Language Processing',
                            'Computer Vision',
                            'AI Applications',
                            'Ethics in AI',
                            'AI Frameworks',
                            'Data Preparation for AI',
                            'AI Project Lifecycle'
                        ]
                    },
                    {
                        'title': 'AI Techniques',
                        'lessons': [
                            'Supervised Learning',
                            'Unsupervised Learning',
                            'Reinforcement Learning',
                            'Convolutional Networks',
                            'Recurrent Networks',
                            'Transformers & BERT',
                            'Generative Models',
                            'AI in Practice',
                            'Model Evaluation',
                            'AI Deployment',
                            'Explainable AI',
                            'Future of AI'
                        ]
                    }
                ]
            }
        ]

        created_courses = []
        
        with transaction.atomic():
            for course_data in courses_data:
                self.stdout.write(f'Creating course: {course_data["title"]}')
                
                # Create course
                course = Course.objects.create(
                    title=course_data['title'],
                    description=course_data['description'],
                    is_active=True
                )
                created_courses.append(course)
                
                # Add instructor to course (many-to-many)
                course.instructors.add(instructor)
                
                # Create playlists and lessons
                for playlist_index, playlist_data in enumerate(course_data['playlists']):
                    playlist = Playlist.objects.create(
                        title=playlist_data['title'],
                        course=course,
                        order=playlist_index
                    )
                    
                    self.stdout.write(f'  Creating playlist: {playlist.title} with {len(playlist_data["lessons"])} lessons')
                    
                    # Create lessons
                    for lesson_index, lesson_title in enumerate(playlist_data['lessons']):
                        Lesson.objects.create(
                            title=lesson_title,
                            playlist=playlist,
                            order=lesson_index,
                            notes=f"Complete this lesson to understand {lesson_title.lower()}.",
                            video_url=''  # Empty URL to be filled later
                        )
        
        # Summary
        self.stdout.write(self.style.SUCCESS('=' * 50))
        self.stdout.write(self.style.SUCCESS('Database population completed successfully!'))
        self.stdout.write(self.style.SUCCESS(f'Created {len(created_courses)} courses:'))
        for course in created_courses:
            playlist_count = course.playlists.count()
            lesson_count = Lesson.objects.filter(playlist__course=course).count()
            self.stdout.write(self.style.SUCCESS(
                f'  - {course.title}: {playlist_count} playlists, {lesson_count} lessons'
            ))
        self.stdout.write(self.style.SUCCESS('=' * 50))
        
        # Verify data
        total_lessons = Lesson.objects.count()
        total_playlists = Playlist.objects.count()
        self.stdout.write(self.style.SUCCESS(f'Total: {total_playlists} playlists, {total_lessons} lessons'))

    def get_or_create_instructor(self):
        """Get or create a default instructor user"""
        instructor_email = 'instructor@example.com'
        
        try:
            instructor = User.objects.get(email=instructor_email)
            self.stdout.write(f'Found existing instructor: {instructor.get_full_name()}')
        except User.DoesNotExist:
            # Create instructor
            instructor = User.objects.create_user(
                username='instructor',
                email=instructor_email,
                password='instructor123',
                first_name='John',
                last_name='Doe',
                user_type='instructor'
            )
            self.stdout.write(f'Created new instructor: {instructor.get_full_name()}')
        
        return instructor