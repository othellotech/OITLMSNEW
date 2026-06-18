// Client-side validation for registration and login

document.addEventListener('DOMContentLoaded', function() {
    // Registration form validation
    const registrationForm = document.querySelector('form[action=""]');
    if (registrationForm && window.location.pathname === '/') {
        setupRegistrationValidation(registrationForm);
    }
    
    // Login form validation
    const loginForm = document.querySelector('.login-card form');
    if (loginForm && window.location.pathname.includes('/login/')) {
        setupLoginValidation(loginForm);
    }
});

function setupRegistrationValidation(form) {
    const firstName = form.querySelector('input[name="first_name"]');
    const lastName = form.querySelector('input[name="last_name"]');
    const email = form.querySelector('input[name="email"]');
    const password1 = form.querySelector('input[name="password1"]');
    const password2 = form.querySelector('input[name="password2"]');
    const accessCode = form.querySelector('input[name="access_code"]');
    
    // Add real-time validation
    if (password1) {
        password1.addEventListener('input', function() {
            validatePasswordStrength(this.value, firstName?.value, lastName?.value, email?.value);
        });
    }
    
    if (email) {
        email.addEventListener('blur', function() {
            checkEmailExists(this.value);
        });
    }
    
    if (accessCode) {
        accessCode.addEventListener('blur', function() {
            validateAccessCode(this.value);
        });
    }
    
    form.addEventListener('submit', function(e) {
        let isValid = true;
        
        // Clear previous error messages
        clearErrors(form);
        
        // Validate first name
        if (firstName && !firstName.value.trim()) {
            showError(firstName, 'First name is required');
            isValid = false;
        } else if (firstName && firstName.value.trim().length < 2) {
            showError(firstName, 'First name must be at least 2 characters');
            isValid = false;
        }
        
        // Validate last name
        if (lastName && !lastName.value.trim()) {
            showError(lastName, 'Last name is required');
            isValid = false;
        } else if (lastName && lastName.value.trim().length < 2) {
            showError(lastName, 'Last name must be at least 2 characters');
            isValid = false;
        }
        
        // Validate email
        const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
        if (email && !email.value.trim()) {
            showError(email, 'Email is required');
            isValid = false;
        } else if (email && !emailRegex.test(email.value)) {
            showError(email, 'Please enter a valid email address');
            isValid = false;
        }
        
        // Validate password
        const passwordValidation = validatePasswordStrength(
            password1?.value || '', 
            firstName?.value || '', 
            lastName?.value || '', 
            email?.value || ''
        );
        
        if (password1 && !password1.value) {
            showError(password1, 'Password is required');
            isValid = false;
        } else if (passwordValidation !== true) {
            showError(password1, passwordValidation);
            isValid = false;
        }
        
        // Validate password confirmation
        if (password2 && password1 && password1.value !== password2.value) {
            showError(password2, 'Passwords do not match');
            isValid = false;
        }
        
        // Validate access code
        if (accessCode && !accessCode.value.trim()) {
            showError(accessCode, 'Access code is required');
            isValid = false;
        } else if (accessCode && accessCode.value.trim().length < 6) {
            showError(accessCode, 'Access code must be at least 6 characters');
            isValid = false;
        }
        
        if (!isValid) {
            e.preventDefault();
        }
    });
}

function setupLoginValidation(form) {
    const email = form.querySelector('input[name="email"]');
    const password = form.querySelector('input[name="password"]');
    
    // Add real-time validation
    if (email) {
        email.addEventListener('blur', function() {
            const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
            if (this.value && !emailRegex.test(this.value)) {
                showError(this, 'Please enter a valid email address');
            } else {
                clearFieldError(this);
            }
        });
    }
    
    form.addEventListener('submit', function(e) {
        let isValid = true;
        clearErrors(form);
        
        if (email && !email.value.trim()) {
            showError(email, 'Email is required');
            isValid = false;
        } else if (email) {
            const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
            if (!emailRegex.test(email.value)) {
                showError(email, 'Please enter a valid email address');
                isValid = false;
            }
        }
        
        if (password && !password.value) {
            showError(password, 'Password is required');
            isValid = false;
        } else if (password && password.value.length < 8) {
            showError(password, 'Password must be at least 8 characters');
            isValid = false;
        }
        
        if (!isValid) {
            e.preventDefault();
        }
    });
}

function validatePasswordStrength(password, firstName, lastName, email) {
    if (password.length < 8) {
        return 'Password must be at least 8 characters long';
    }
    
    // Check if password contains name
    if (firstName && firstName.toLowerCase() && password.toLowerCase().includes(firstName.toLowerCase())) {
        return 'Password cannot contain your first name';
    }
    
    if (lastName && lastName.toLowerCase() && password.toLowerCase().includes(lastName.toLowerCase())) {
        return 'Password cannot contain your last name';
    }
    
    // Check if password contains email username
    if (email) {
        const emailUsername = email.split('@')[0].toLowerCase();
        if (emailUsername && password.toLowerCase().includes(emailUsername)) {
            return 'Password cannot contain your email username';
        }
    }
    
    // Check for common weak passwords
    const commonPasswords = ['password', '12345678', 'qwerty123', 'admin123', 'letmein', 'welcome1', 'password123'];
    if (commonPasswords.includes(password.toLowerCase())) {
        return 'Password is too common. Please choose a stronger password';
    }
    
    // Check for at least one number
    if (!/\d/.test(password)) {
        return 'Password should contain at least one number';
    }
    
    // Check for at least one uppercase letter
    if (!/[A-Z]/.test(password)) {
        return 'Password should contain at least one uppercase letter';
    }
    
    return true;
}

function checkEmailExists(email) {
    if (!email) return;
    
    // This would typically be an AJAX call to the server
    // For now, we'll just show a warning if the format is invalid
    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    if (!emailRegex.test(email)) {
        showError(document.querySelector('input[name="email"]'), 'Please enter a valid email address');
        return;
    }
    
    // You can uncomment this for AJAX email existence check
    /*
    fetch(`/check-email/?email=${encodeURIComponent(email)}`)
        .then(response => response.json())
        .then(data => {
            if (data.exists) {
                showError(document.querySelector('input[name="email"]'), 'This email is already registered. Please login instead.');
            }
        })
        .catch(error => console.error('Error:', error));
    */
}

function validateAccessCode(code) {
    // Basic format validation
    if (code && code.length < 6) {
        showError(document.querySelector('input[name="access_code"]'), 'Access code must be at least 6 characters');
    } else {
        clearFieldError(document.querySelector('input[name="access_code"]'));
    }
}

function showError(element, message) {
    if (!element) return;
    
    // Remove any existing error for this field
    clearFieldError(element);
    
    // Add error class to input
    element.classList.add('error');
    
    // Create error message element
    const errorDiv = document.createElement('div');
    errorDiv.className = 'error-message';
    errorDiv.style.color = '#f44336';
    errorDiv.style.fontSize = '0.8rem';
    errorDiv.style.marginTop = '0.3rem';
    errorDiv.textContent = message;
    
    // Insert after the input
    element.parentNode.appendChild(errorDiv);
}

function clearErrors(form) {
    // Remove all error messages
    const errorMessages = form.querySelectorAll('.error-message');
    errorMessages.forEach(msg => msg.remove());
    
    // Remove error classes from inputs
    const errorInputs = form.querySelectorAll('.error');
    errorInputs.forEach(input => input.classList.remove('error'));
}

function clearFieldError(element) {
    if (!element) return;
    
    // Remove error class
    element.classList.remove('error');
    
    // Remove error message if exists
    const errorMsg = element.parentNode.querySelector('.error-message');
    if (errorMsg) {
        errorMsg.remove();
    }
}

// Password strength indicator (optional)
function addPasswordStrengthIndicator(passwordField) {
    const indicator = document.createElement('div');
    indicator.className = 'password-strength';
    indicator.style.marginTop = '0.5rem';
    indicator.style.fontSize = '0.8rem';
    passwordField.parentNode.appendChild(indicator);
    
    passwordField.addEventListener('input', function() {
        const strength = getPasswordStrength(this.value);
        indicator.innerHTML = strength.message;
        indicator.style.color = strength.color;
    });
}

function getPasswordStrength(password) {
    let score = 0;
    
    if (password.length >= 8) score++;
    if (password.length >= 12) score++;
    if (/[A-Z]/.test(password)) score++;
    if (/[0-9]/.test(password)) score++;
    if (/[^A-Za-z0-9]/.test(password)) score++;
    
    switch(score) {
        case 0:
        case 1:
            return { message: '🔴 Weak password', color: '#f44336' };
        case 2:
        case 3:
            return { message: '🟡 Medium password', color: '#ff9800' };
        case 4:
        case 5:
            return { message: '🟢 Strong password', color: '#4caf50' };
        default:
            return { message: '', color: '' };
    }
}