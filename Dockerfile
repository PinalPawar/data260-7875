# Use Nginx as the base image
FROM nginx:alpine

# Remove default Nginx HTML files
RUN rm -rf /usr/share/nginx/html/*

# Copy all frontend files (HTML, CSS, JS) into the Nginx web root
COPY . /usr/share/nginx/html/

# Overwrite default nginx config to listen on 8675
COPY nginx.conf /etc/nginx/nginx.conf

# Expose port 8675
EXPOSE 8675

# Start Nginx
CMD ["nginx", "-g", "daemon off;"]
